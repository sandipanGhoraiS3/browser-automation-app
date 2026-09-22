import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from jsonschema import validate
from app.agent.providers import decide, append_result, compact_messages
from app.browser.state import observe, result_text
from app.config import settings
from app.database.store import store, now
from app.services.security import redact
from app.agent.tools import ToolRegistry

SYSTEM = Path(__file__).with_name('system.md').read_text()
CONFIRM = {'name': 'request_confirmation', 'description': 'Request permission for the exact next high-impact action.', 'parameters': {'type': 'object', 'properties': {'description': {'type': 'string'}}, 'required': ['description'], 'additionalProperties': False}}
CLOSE = re.compile(r'^\s*(?:please\s+)?(?:close (?:the )?browser|exit browser|terminate browser)[.!]?\s*$', re.I)
RISK = re.compile(r'\b(delete|remove|purchase|buy|pay|checkout|send|submit|publish|transfer|save changes|confirm order)\b', re.I)
TOOL_RESULT_LIMITS = {'agent': 32000}
DEFAULT_TOOL_RESULT_LIMIT = 8000

def tools_for(session):
    return ToolRegistry(session).definitions() + [CONFIRM]

def valid_refs(arguments, snapshot):
    available = set(re.findall(r'\[ref=([^\]]+)\]', snapshot))
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (key.lower().endswith('ref') or key.lower().endswith('target')) and isinstance(item, str) and item not in available:
                    raise ValueError('Reference is absent from the current snapshot. Inspect the new snapshot and choose again.')
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(arguments)

async def confirmation(session, description):
    session.confirmation = asyncio.get_running_loop().create_future()
    session.pending_confirmation = {'id': str(uuid.uuid4()), 'description': redact(description)}
    await session.emit({'type': 'confirmation', **session.pending_confirmation})
    try:
        return await session.confirmation
    finally:
        session.confirmation = None
        session.pending_confirmation = None
        await session.emit({'type': 'confirmation_cleared'})

async def run(session, message, provider, use_knowledge=None, knowledge_domain_id=None):
    run_id = str(uuid.uuid4())
    store.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?)', (run_id, session.session_id, 'running', now(), None, None))
    session.activity, session.partial = [], ''
    session.active_skills = {}
    session.use_knowledge = use_knowledge
    session.knowledge_domain_id = knowledge_domain_id
    session.rag_sources = []
    session.rag_debug = None
    await session.emit({'type': 'status', 'status': 'running'})
    final_status, error = 'completed', None
    async def say(text, role='assistant', include_rag=False):
        metadata = None
        if include_rag and session.rag_sources:
            metadata = {
                'sources': session.rag_sources,
                'retrieval': {
                    'source_count': len({item['document_id'] for item in session.rag_sources}),
                    'chunk_count': len(session.rag_sources),
                    'domain_id': session.knowledge_domain_id,
                },
            }
            if settings.debug_rag and session.rag_debug:
                metadata['rag_debug'] = session.rag_debug
        await session.emit({'type': 'message', 'message': store.message(session.session_id, role, text, metadata)})
    try:
        if CLOSE.fullmatch(message):
            await session.mcp.stop()
            session.url, session.tabs, session.screenshot = '', '', 0
            await session.emit({'type': 'browser', **session.browser_state()})
            await say('Browser closed. Your conversation is saved.')
            return
        selected_skill = session.skills.resolve_command(message)
        if selected_skill:
            session.active_skills[selected_skill.metadata.name] = selected_skill
            if not session.knowledge_domain_id and selected_skill.metadata.knowledge_domain:
                from app.rag.service import rag_service
                domains = await rag_service.list_domains(session.workspace_id)
                requested = selected_skill.metadata.knowledge_domain.lower()
                match = next((item for item in domains if item['id'] == requested or item['name'].lower() == requested), None)
                if match:
                    session.knowledge_domain_id = match['id']
                    session.use_knowledge = True
            await session.emit({'type': 'activity', 'id': str(uuid.uuid4()), 'category': 'skill', 'name': 'Skill loaded', 'description': selected_skill.metadata.display_name, 'status': 'success'})
        history = store.conversation(session.session_id)['messages'][-30:]
        messages = [{'role': m['role'] if m['role'] in ('user', 'assistant') else 'assistant', 'content': m['content']} for m in history]
        tools = tools_for(session)
        executor = ToolRegistry(session, provider)
        schemas = {t['name']: t['parameters'] for t in tools}
        failures = {}
        approved = False
        for _ in range(settings.max_agent_steps):
            session.last_activity = time.time()
            snapshot = session.snapshot
            discovered = session.skills.discover()
            catalog = json.dumps([s['metadata'] for s in discovered['skills']])
            skills_context = '\n\n'.join(s.markdown for s in session.active_skills.values())
            context = SYSTEM + '\n\nAVAILABLE SKILLS:\n' + catalog + '\n\nACTIVE JOB INSTRUCTIONS (subordinate to tool security and user consent):\n' + skills_context + '\n\nCURRENT BROWSER OBSERVATION:\n' + snapshot[-45000:]
            decision = await decide(provider, context, compact_messages(messages), tools, session.emit)
            if not decision.calls:
                await say(decision.text or 'Task complete.', include_rag=True)
                break
            if len(decision.calls) != 1:
                raise RuntimeError('Model returned multiple simultaneous actions. Retry with a model supporting sequential tool use.')
            call = decision.calls[0]
            name, args = call['name'], call['arguments']
            if name not in schemas:
                raise ValueError('Model requested an unavailable tool.')
            validate(args, schemas[name])
            if decision.text:
                await say(decision.text)
            if name == 'request_confirmation':
                approved = await confirmation(session, args['description'])
                append_result(messages, decision, 'Approved for the next action only.' if approved else 'Denied. Do not perform this action.', provider)
                continue
            action_id, started = str(uuid.uuid4()), time.monotonic()
            category = executor.category(name)
            activity = {'type': 'activity', 'id': action_id, 'category': category, 'name': name.removeprefix(category + '_').replace('_', ' ').title(), 'description': redact(str(args.get('element') or args.get('url') or args.get('path') or args.get('destination') or args.get('name') or {'browser': 'Using the current browser state', 'agent': 'Parallel subtasks', 'knowledge': 'Workspace knowledge', 'skill': 'Skill operation'}.get(category, 'Downloads operation'))), 'status': 'running'}
            await session.emit(activity)
            store.execute('INSERT INTO tool_calls VALUES(?,?,?,?,?,?,?)', (action_id, run_id, name, 'running', now(), None, None))
            result, tool_status = '', 'success'
            signature = name + json.dumps(args, sort_keys=True)
            try:
                if failures.get(signature, 0) > settings.max_tool_retries:
                    raise RuntimeError('Retry limit reached for this action. Choose a different approach.')
                if category == 'browser':
                    valid_refs(args, snapshot)
                risky = executor.needs_confirmation(name, args) or (category == 'browser' and (RISK.search(json.dumps(args)) or name in ('browser_evaluate', 'browser_file_upload')))
                if risky and not approved:
                    approved = await confirmation(session, f"Allow {activity['name']}: {activity['description']}?")
                    if not approved:
                        raise ValueError('User declined the action. Do not perform it.')
                approved = False
                result = await executor.execute(name, args)
            except asyncio.CancelledError:
                tool_status = 'cancelled'
                result = 'Cancelled by user.'
                raise
            except Exception as exc:
                tool_status = 'failed'
                result = redact(str(exc))
                failures[signature] = failures.get(signature, 0) + 1
            finally:
                activity.update(status=tool_status, duration=round(time.monotonic() - started, 2), details=redact(result[:2000]) if tool_status != 'success' else f'{category.title()} action completed.')
                store.execute('UPDATE tool_calls SET status=?,completed_at=?,error=? WHERE id=?', (tool_status, now(), redact(result) if tool_status == 'failed' else None, action_id))
                await session.emit(activity)
            fresh = snapshot
            if category == 'browser' and session.mcp.status == 'connected':
                fresh = await observe(session, screenshot=True)
            tools = tools_for(session)
            schemas = {t['name']: t['parameters'] for t in tools}
            result_limit = TOOL_RESULT_LIMITS.get(category, DEFAULT_TOOL_RESULT_LIMIT)
            append_result(messages, decision, redact(result[:result_limit]) + '\nFRESH OBSERVATION:\n' + fresh[-12000:], provider)
        else:
            final_status = 'limit_reached'
            await say('Maximum agent steps reached. The browser remains open; send a follow-up to continue.')
    except asyncio.CancelledError:
        final_status = 'cancelled'
        await say('Task stopped. Browser session remains open.')
    except Exception as exc:
        final_status, error = 'failed', redact(str(exc))
        await say(error, 'error')
    finally:
        for skill in session.active_skills.values():
            await session.emit({'type': 'activity', 'id': str(uuid.uuid4()), 'category': 'skill', 'name': 'Skill ' + ('completed' if final_status == 'completed' else final_status.replace('_', ' ')), 'description': skill.metadata.display_name, 'status': 'success' if final_status == 'completed' else 'cancelled' if final_status == 'cancelled' else 'failed', 'details': error or 'See task results above.'})
        store.execute('UPDATE agent_runs SET status=?,completed_at=?,error=? WHERE id=?', (final_status, now(), error, run_id))
        session.last_activity = time.time()
        await session.emit({'type': 'status', 'status': 'idle'})


