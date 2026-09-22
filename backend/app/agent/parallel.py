import asyncio
import contextlib
import json
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from jsonschema import validate
from pydantic import BaseModel, ConfigDict, Field
from app.agent.providers import decide, append_result, compact_messages
from app.browser.state import observe
from app.sessions.manager import BrowserSession

SYSTEM = Path(__file__).with_name('system.md').read_text()
RISK = re.compile(r'\b(delete|remove|purchase|buy|pay|checkout|send|submit|publish|transfer|save changes|confirm order)\b', re.I)
SUBAGENT_BLOCKED = {'agent_run_parallel', 'browser_evaluate', 'browser_file_upload'}
RISKY_BROWSER_ACTIONS = {'browser_click', 'browser_drag', 'browser_select_option', 'browser_press_key'}
RESEARCH_MIN_SOURCES = 3
RESEARCH_MAX_STEPS = 20
DEFAULT_MAX_STEPS = 12
RATE_LIMIT_RETRIES = 2
RESEARCH_PROTOCOL = f'''\
WEB RESEARCH QUALITY STANDARD (mandatory for research roles):
- Browse the live web; do not answer from model memory alone.
- Investigate the assigned angle deeply enough to add useful detail, not a one-paragraph overview.
- Open and read at least {RESEARCH_MIN_SOURCES} independent source pages. Search-result snippets do not count as sources.
- Prefer primary/official sources for dates, offices, awards, and records. Use reputable secondary sources for context.
- Cross-check important facts. If credible sources disagree, state the disagreement instead of guessing.
- Return structured Markdown with findings, key dates, uncertainties, and numbered sources.
- For every source include its title, publisher, direct URL, and supported claims. Never invent citations.
'''


def _is_evidence_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return False
    host = parsed.netloc.lower().removeprefix('www.')
    search_hosts = ('google.', 'bing.', 'duckduckgo.', 'search.yahoo.')
    return not (
        any(host.startswith(prefix) for prefix in search_hosts)
        or host.endswith(('.google.com', '.bing.com', '.duckduckgo.com'))
    )


def _independent_source_count(urls: list[str]) -> int:
    return len({urlparse(url).netloc.lower().removeprefix('www.') for url in urls})


def _browser_research_available(definitions: list[dict]) -> bool:
    actionable = {
        'browser_initialize', 'browser_navigate', 'browser_click',
        'browser_type', 'browser_press_key', 'browser_select_option',
    }
    return any(tool['name'] in actionable for tool in definitions)


def _continue_research(messages, decision, task: str, source_count: int):
    messages.extend([
        {'role': 'assistant', 'content': decision.text or 'Initial findings are incomplete.'},
        {'role': 'user', 'content': (
            f'Continue the original research task: {task}\n'
            f'Only {source_count} independent source page(s) have been opened. '
            f'Open and read at least {RESEARCH_MIN_SOURCES}, cross-check important claims, then return '
            'structured findings with direct source URLs. Search-result pages do not count.'
        )},
    ])


def _completed_result(task, text: str, source_urls: list[str], step_limit_reached=False):
    result = {'role': task.role, 'task': task.task, 'status': 'completed', 'result': text}
    if task.role == 'research':
        source_count = _independent_source_count(source_urls)
        result.update({
            'sources': source_urls,
            'research_quality': (
                'source-verified' if source_count >= RESEARCH_MIN_SOURCES
                else f'limited: only {source_count} independent source publisher(s) opened'
            ),
            'step_limit_reached': step_limit_reached,
        })
    return result


def _is_rate_limit_error(exc: Exception) -> bool:
    status = getattr(exc, 'status_code', None)
    response = getattr(exc, 'response', None)
    status = status or getattr(response, 'status_code', None)
    text = str(exc).lower()
    return status == 429 or 'rate limit' in text or 'too many requests' in text


def _retry_delay(exc: Exception, attempt: int) -> float:
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    try:
        retry_after_ms = headers.get('retry-after-ms')
        if retry_after_ms:
            return min(max(float(retry_after_ms) / 1000, 0.5), 30)
        retry_after = headers.get('retry-after')
        if retry_after:
            return min(max(float(retry_after), 0.5), 30)
    except (TypeError, ValueError):
        pass
    return min(5 * (2 ** attempt), 30)


async def _model_decision(provider, context, messages, definitions, emit, model_gate=None):
    async def request():
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return await decide(provider, context, messages, definitions, emit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt == RATE_LIMIT_RETRIES:
                    raise
                await asyncio.sleep(_retry_delay(exc, attempt))

    if model_gate is None:
        return await request()
    async with model_gate:
        return await request()


def _valid_refs(arguments, snapshot):
    available = set(re.findall(r'\[ref=([^\]]+)\]', snapshot))

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (key.lower().endswith('ref') or key.lower().endswith('target')) and isinstance(item, str) and item not in available:
                    raise ValueError('Reference is absent from the current snapshot.')
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(arguments)


class ParallelTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['research', 'browser', 'knowledge', 'file_analysis'] = 'research'
    task: str = Field(min_length=5, max_length=4000)


class ParallelArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tasks: list[ParallelTask] = Field(min_length=2, max_length=4)


async def _subagent(parent, task: ParallelTask, provider: str, model_gate=None):
    from app.agent.tools import ToolRegistry
    session = None
    try:
        session = BrowserSession(f'{parent.session_id}-sub-{uuid.uuid4()}', parent.workspace_id)
        session.use_knowledge = getattr(parent, 'use_knowledge', None)
        session.knowledge_domain_id = getattr(parent, 'knowledge_domain_id', None)
        messages = [{'role': 'user', 'content': task.task}]
        source_urls = []
        quality_retries = 0

        async def collect(_event):
            return None

        max_steps = RESEARCH_MAX_STEPS if task.role == 'research' else DEFAULT_MAX_STEPS
        for _ in range(max_steps):
            registry = ToolRegistry(session, provider)
            definitions = [tool for tool in registry.definitions() if tool['name'] not in SUBAGENT_BLOCKED]
            if task.role == 'research':
                # Research workers gather evidence only. The parent owns all file output.
                definitions = [tool for tool in definitions if tool['name'].startswith('browser_')]
            schemas = {tool['name']: tool['parameters'] for tool in definitions}
            research_context = '\n\n' + RESEARCH_PROTOCOL if task.role == 'research' else ''
            context = SYSTEM + f'\n\nSUB-AGENT ROLE: {task.role}\nComplete only this independent subtask and return concise structured findings. Use snapshots for read-only page extraction; browser evaluation and file upload are unavailable. Do not perform high-impact or destructive actions.{research_context}\n\nCURRENT BROWSER OBSERVATION:\n' + session.snapshot[-30000:]
            decision = await _model_decision(
                provider, context, compact_messages(messages), definitions, collect, model_gate,
            )
            if not decision.calls:
                source_count = _independent_source_count(source_urls)
                if (
                    task.role == 'research'
                    and source_count < RESEARCH_MIN_SOURCES
                    and _browser_research_available(definitions)
                    and quality_retries < 2
                ):
                    quality_retries += 1
                    _continue_research(messages, decision, task.task, source_count)
                    continue
                return _completed_result(task, decision.text, source_urls)
            if len(decision.calls) != 1:
                raise RuntimeError('Sub-agent returned multiple simultaneous actions.')
            call = decision.calls[0]
            category = registry.category(call['name'])
            try:
                if call['name'] not in schemas:
                    raise ValueError('That tool is unavailable to sub-agents. Choose a safe read-only alternative.')
                validate(call['arguments'], schemas[call['name']])
                risky = registry.needs_confirmation(call['name'], call['arguments']) or (
                    category == 'browser'
                    and call['name'] in RISKY_BROWSER_ACTIONS
                    and RISK.search(json.dumps(call['arguments']))
                )
                if risky:
                    raise ValueError('This action requires user confirmation and cannot be delegated. Choose a safe read-only alternative.')
                if category == 'browser':
                    _valid_refs(call['arguments'], session.snapshot)
                result = await registry.execute(call['name'], call['arguments'])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                fresh = session.snapshot
                if category == 'browser' and session.mcp.status == 'connected':
                    try:
                        fresh = await observe(session, screenshot=False)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                append_result(messages, decision, f'Action failed: {str(exc)[:1000]}\nChoose a safe alternative and continue.\nFRESH OBSERVATION:\n' + fresh[-12000:], provider)
                continue
            fresh = session.snapshot
            if category == 'browser' and session.mcp.status == 'connected':
                # Semantic snapshots are sufficient for background source extraction.
                fresh = await observe(session, screenshot=False)
                current_url = getattr(session, 'url', '')
                if _is_evidence_url(current_url) and current_url not in source_urls:
                    source_urls.append(current_url)
            append_result(messages, decision, result[:8000] + '\nFRESH OBSERVATION:\n' + fresh[-12000:], provider)
        final_context = (
            SYSTEM
            + f'\n\nSUB-AGENT ROLE: {task.role}\n'
            + 'The browsing step budget is exhausted. Do not perform another action. '
            + 'Using only evidence already present in the conversation, return the best concise '
            + 'structured findings now. Preserve direct source URLs and inline source numbers. '
            + 'Explicitly label gaps or unverified claims; do not fill them from memory.'
            + '\n\nCURRENT BROWSER OBSERVATION:\n'
            + session.snapshot[-30000:]
        )
        final = await _model_decision(
            provider, final_context, compact_messages(messages), [], collect, model_gate,
        )
        text = final.text.strip() or (
            'No reliable findings could be synthesized from the evidence gathered '
            'within the browsing budget.'
        )
        return _completed_result(task, text, source_urls, step_limit_reached=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {'role': task.role, 'task': task.task, 'status': 'failed', 'error': str(exc)[:1000]}
    finally:
        if session is not None:
            with contextlib.suppress(Exception):
                await session.close()

async def run_parallel(parent, args: ParallelArgs, provider: str):
    # Azure deployments commonly enforce low request/concurrent-call quotas.
    # Serialize only model calls; browser I/O across agents still overlaps.
    model_gate = asyncio.Semaphore(1) if provider == 'azure' else None

    async def tracked(task):
        activity_id = str(uuid.uuid4())
        started = asyncio.get_running_loop().time()
        if hasattr(parent, 'emit'):
            await parent.emit({
                'type': 'activity', 'id': activity_id, 'category': 'agent',
                'name': task.role.replace('_', ' ').title() + ' Agent',
                'description': task.task, 'status': 'running',
            })
        result = await _subagent(parent, task, provider, model_gate)
        if hasattr(parent, 'emit'):
            await parent.emit({
                'type': 'activity', 'id': activity_id, 'category': 'agent',
                'name': task.role.replace('_', ' ').title() + ' Agent',
                'description': task.task,
                'status': 'success' if result['status'] == 'completed' else 'failed',
                'duration': round(asyncio.get_running_loop().time() - started, 2),
                'details': result.get('result') or result.get('error', 'Subtask failed.'),
            })
        return result

    results = await asyncio.gather(*(tracked(task) for task in args.tasks))
    completed = sum(result['status'] == 'completed' for result in results)
    research_results = [result for result in results if result['role'] == 'research']
    unique_sources = {
        url for result in research_results for url in result.get('sources', [])
    }
    verified_research = sum(
        result.get('research_quality') == 'source-verified' for result in research_results
    )
    return json.dumps({
        'subtasks': results,
        'completed': completed,
        'failed': len(results) - completed,
        'research_summary': {
            'verified_subtasks': verified_research,
            'research_subtasks': len(research_results),
            'unique_source_pages': len(unique_sources),
        },
        'orchestration_note': 'Synthesize the final response from these results. Preserve inline citations and direct URLs, reconcile conflicts, and do not repeat completed subtasks in the main browser. Report limited or unverified fields clearly.',
    }, ensure_ascii=False)





