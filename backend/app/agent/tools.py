import asyncio
import json
from pathlib import Path
from app.file_agent.tools import FILE_TOOLS, tool_definitions
from app.file_agent.models import EmptyArgs, PathArgs, WriteArgs
from app.skills.models import SkillName, CreateSkill
from app.browser.state import capture, result_text
from app.browser.downloads import detect_downloads
from app.agent.parallel import ParallelArgs
from app.rag.models import RagSearchArgs

KNOWLEDGE_TOOLS = {
    'list': (EmptyArgs, 'List notes in the active workspace knowledge store.'),
    'read': (PathArgs, 'Read a UTF-8 note from the active workspace knowledge store.'),
    'create': (WriteArgs, 'Create a new note in the active workspace knowledge store. Never overwrites an existing note.'),
}

SKILL_TOOLS = {
    'list_skills': (EmptyArgs, 'Discover reusable job skills and descriptions.'),
    'load_skill': (SkillName, 'Read a reusable job skill without executing it.'),
    'run_skill': (SkillName, 'Load a skill into the current task context. Follow its semantic steps using browser and file tools.'),
    'create_skill': (CreateSkill, 'Save a completed workflow as a reusable Markdown skill. Never overwrite, include secrets, or store page references or coordinates.'),
}

BROWSER_INITIALIZE = {
    'name': 'browser_initialize',
    'description': 'Initialize the browser only when the user request requires website interaction or downloading from a website. Do not use for normal conversation or local file operations.',
    'parameters': EmptyArgs.model_json_schema(),
}

PARALLEL_AGENT = {
    'name': 'agent_run_parallel',
    'description': 'Run 2 to 4 genuinely independent research, browser, knowledge, or file-analysis subtasks concurrently and return structured results. Use for substantial web-researched reports or documents by assigning distinct evidence angles to research agents. Do not use for normal conversation, simple file creation without research, or dependent steps.',
    'parameters': ParallelArgs.model_json_schema(),
}

RAG_SEARCH = {
    'name': 'rag_search',
    'description': (
        'Search the current workspace Azure knowledge base for internal/company-specific facts. '
        'Use this when the request refers to "our" policies, procedures, documents, operations, '
        'or other workspace knowledge. Do not use it for trivial arithmetic, generic knowledge, or live web facts. '
        'Workspace and selected-domain isolation are enforced by the backend.'
    ),
    'parameters': RagSearchArgs.model_json_schema(),
}

class ToolRegistry:
    def __init__(self, session, provider=None):
        self.session = session
        self.provider = provider

    def definitions(self):
        blocked = {'browser_close', 'browser_run_code', 'browser_run_code_unsafe'}
        browser = [{'name': t.name, 'description': t.description or t.name, 'parameters': t.inputSchema} for t in self.session.mcp.tools if t.name not in blocked]
        if self.session.mcp.status != 'connected':
            browser = [BROWSER_INITIALIZE]
        skills = [{'name': 'skill_' + name, 'description': desc, 'parameters': schema.model_json_schema()} for name, (schema, desc) in SKILL_TOOLS.items()]
        knowledge = [{'name': 'knowledge_' + name, 'description': desc, 'parameters': schema.model_json_schema()} for name, (schema, desc) in KNOWLEDGE_TOOLS.items()]
        rag = [] if getattr(self.session, 'use_knowledge', None) is False else [RAG_SEARCH]
        return browser + tool_definitions() + skills + knowledge + rag + [PARALLEL_AGENT]

    @staticmethod
    def category(name):
        return 'file' if name.startswith('file_') else 'skill' if name.startswith('skill_') else 'knowledge' if name.startswith(('knowledge_', 'rag_')) else 'agent' if name.startswith('agent_') else 'browser'

    @staticmethod
    def needs_confirmation(name, args):
        return name == 'file_delete_file' or (name == 'file_write_file' and args.get('overwrite', False))

    async def execute(self, name, args):
        category = self.category(name)
        files = self.session.files
        if category == 'agent':
            if not self.provider:
                raise ValueError('Parallel agents require the active model provider.')
            from app.agent.parallel import run_parallel
            return await run_parallel(self.session, ParallelArgs.model_validate(args), self.provider)
        if category == 'knowledge':
            if name == 'rag_search':
                from app.rag.service import rag_service, tool_payload
                parsed = RagSearchArgs.model_validate(args)
                result = await rag_service.query(
                    self.session.workspace_id, parsed.query, self.session.knowledge_domain_id,
                    queries=parsed.queries, document_id=parsed.document_id,
                    content_type=parsed.content_type,
                )
                self.session.rag_sources = result.sources
                self.session.rag_debug = result.debug
                return tool_payload(result)
            operation = name.removeprefix('knowledge_')
            schema, _ = KNOWLEDGE_TOOLS[operation]
            parsed = schema.model_validate(args).model_dump()
            if operation == 'list':
                result = await self.session.knowledge.execute('list_directory', {'path': '.'})
            elif operation == 'read':
                result = await self.session.knowledge.execute('read_file', parsed)
            else:
                parsed['overwrite'] = False
                result = await self.session.knowledge.execute('create_file', parsed)
            return json.dumps(result, ensure_ascii=False)
        if category == 'browser':
            if name == 'browser_initialize':
                await self.session.mcp.start()
                return 'Browser initialized for the requested website interaction.'
            # Keep all browser-created artifacts in the session sandbox.
            if name == 'browser_take_screenshot' and args.get('filename'):
                raise ValueError('Use file_save_screenshot to save a named image in PC Downloads.')
            if name == 'browser_file_upload':
                args = dict(args)
                args['paths'] = [str(files.policy.resolve(p)) for p in args.get('paths', [])]
            response = await self.session.mcp.call(name, args)
            text = result_text(response)
            if response.isError:
                raise ValueError(text)
            detected = await detect_downloads(self.session, text)
            return text + ('\nCompleted downloads: ' + json.dumps(detected) if detected else '')
        if category == 'file':
            operation = name.removeprefix('file_')
            schema, _ = FILE_TOOLS[operation]
            parsed = schema.model_validate(args).model_dump()
            if operation == 'save_screenshot':
                await self.session.mcp.start()
                shot = await capture(self.session, parsed['mode'])
                result = await files.import_artifact(shot['path'], parsed['path'])
            elif operation == 'list_downloads':
                result = [{k: v for k, v in d.items() if k != 'source'} for d in self.session.downloads.values()]
            elif operation == 'save_download':
                download = self.session.downloads.get(parsed['download_id'])
                if not download:
                    raise ValueError('Completed download not found. Use file_list_downloads to inspect available files.')
                if download.get('path'):
                    result = {'ok': True, 'path': download['path'], 'bytes': download['bytes']}
                else:
                    source = Path(download['source'])
                    if not source.resolve().is_relative_to(self.session.mcp.directory.resolve()):
                        raise ValueError('Download source is outside the session directory.')
                    result = await files.import_artifact(source, parsed['path'])
            else:
                result = await files.execute(operation, parsed)
            return json.dumps(result, ensure_ascii=False)
        operation = name.removeprefix('skill_')
        schema, _ = SKILL_TOOLS[operation]
        parsed = schema.model_validate(args)
        if operation == 'list_skills':
            discovered = await asyncio.to_thread(self.session.skills.discover)
            return json.dumps({'skills': [s['metadata'] for s in discovered['skills']], 'errors': discovered['errors']})
        if operation == 'create_skill':
            result = await asyncio.to_thread(self.session.skills.create, parsed)
            return json.dumps({'created': result.metadata.name, 'path': f'skills/{result.metadata.name}/skill.md'})
        result = await asyncio.to_thread(self.session.skills.load, parsed.name)
        if operation == 'run_skill':
            self.session.active_skills[result.metadata.name] = result
        return result.markdown




