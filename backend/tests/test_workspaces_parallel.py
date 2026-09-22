import asyncio
import json
import shutil
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import parallel
from app.agent.parallel import ParallelArgs
from app.agent.providers import Decision
from app.database.store import DEFAULT_WORKSPACE_ID, store
from app.file_agent.service import FileService
from app.main import app
from app import workspaces
from app.api import workspace as workspace_api
from app.sessions.manager import manager


def test_workspace_api_isolates_conversations_and_sessions():
    with TestClient(app) as client:
        first = client.post('/api/workspaces', json={'name': 'Isolation A'}).json()
        second = client.post('/api/workspaces', json={'name': 'Isolation B'}).json()
        conversation = client.post('/api/conversations', json={
            'title': 'Only in A', 'workspace_id': first['id'],
        }).json()
        cid = conversation['id']

        assert [item['id'] for item in client.get('/api/conversations', params={'workspace_id': first['id']}).json()] == [cid]
        assert all(item['id'] != cid for item in client.get('/api/conversations', params={'workspace_id': second['id']}).json())
        assert client.get(f'/api/conversations/{cid}', params={'workspace_id': second['id']}).status_code == 404
        assert client.post('/api/sessions', json={'conversation_id': cid, 'workspace_id': second['id']}).status_code == 404
        assert client.get(f'/api/sessions/{cid}', params={'workspace_id': second['id']}).status_code == 404
        assert client.post('/api/chat/stop', json={'session_id': cid, 'workspace_id': second['id']}).status_code == 404
        assert client.get('/api/browser/status', params={'session_id': cid, 'workspace_id': second['id']}).status_code == 404
        assert client.delete(f'/api/conversations/{cid}', params={'workspace_id': second['id']}).status_code == 404
        assert client.delete(f'/api/conversations/{cid}', params={'workspace_id': first['id']}).status_code == 200
        store.execute('DELETE FROM workspaces WHERE id IN (?,?)', (first['id'], second['id']))
        for workspace in (first, second):
            shutil.rmtree(workspaces.DATA / 'workspaces' / workspace['id'], ignore_errors=True)


def test_workspace_delete_closes_sessions_and_cascades_history(monkeypatch):
    removed = []
    async def remove_rag_storage(_workspace_id):
        return {'ok': True}
    monkeypatch.setattr(workspace_api.rag_service, 'delete_workspace', remove_rag_storage)
    def remove_test_storage(workspace_id):
        removed.append(workspace_id)
        shutil.rmtree(workspaces.DATA / 'workspaces' / workspace_id, ignore_errors=True)
    monkeypatch.setattr(workspace_api, 'remove_workspace_storage', remove_test_storage)
    with TestClient(app) as client:
        created = client.post('/api/workspaces', json={'name': 'Delete Me'}).json()
        workspace_id = created['id']
        conversation = client.post('/api/conversations', json={
            'title': 'Disposable conversation', 'workspace_id': workspace_id,
        }).json()
        conversation_id = conversation['id']
        store.message(conversation_id, 'user', 'temporary history')
        assert client.post('/api/sessions', json={
            'conversation_id': conversation_id, 'workspace_id': workspace_id,
        }).status_code == 200
        assert conversation_id in manager.sessions

        response = client.delete(f'/api/workspaces/{workspace_id}')

        assert response.status_code == 200
        assert response.json()['deleted_conversations'] == 1
        assert removed == [workspace_id]
        assert not store.workspace(workspace_id)
        assert not store.conversation(conversation_id)
        assert conversation_id not in manager.sessions
        assert not store.rows('SELECT * FROM messages WHERE conversation_id=?', (conversation_id,))
        assert client.delete(f'/api/workspaces/{DEFAULT_WORKSPACE_ID}').status_code == 409
        assert client.delete(f'/api/workspaces/{uuid.uuid4()}').status_code == 404


def test_workspace_storage_delete_is_scoped_to_selected_workspace(tmp_path, monkeypatch):
    legacy = FileService(tmp_path / 'Downloads', blocked_names={'Orbit Workspaces'})
    monkeypatch.setattr(workspaces, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(workspaces, 'downloads', legacy)
    workspaces.files_for.cache_clear()
    workspaces.skills_for.cache_clear()
    workspaces.knowledge_for.cache_clear()
    workspaces.downloads_for.cache_clear()
    selected_id, retained_id = str(uuid.uuid4()), str(uuid.uuid4())

    selected_internal = workspaces.workspace_root(selected_id)
    retained_internal = workspaces.workspace_root(retained_id)
    selected_internal.joinpath('note.txt').write_text('delete')
    retained_internal.joinpath('note.txt').write_text('keep')
    asyncio.run(workspaces.downloads_for(selected_id).execute(
        'create_file', {'path': 'report.txt', 'content': 'delete'},
    ))
    asyncio.run(workspaces.downloads_for(retained_id).execute(
        'create_file', {'path': 'report.txt', 'content': 'keep'},
    ))

    workspaces.remove_workspace_storage(selected_id)

    assert not selected_internal.exists()
    assert retained_internal.joinpath('note.txt').read_text() == 'keep'
    assert not (legacy.policy.root / 'Orbit Workspaces' / selected_id).exists()
    assert (legacy.policy.root / 'Orbit Workspaces' / retained_id / 'report.txt').read_text() == 'keep'


def test_workspace_download_services_are_isolated_and_default_is_legacy(tmp_path, monkeypatch):
    legacy = FileService(tmp_path / 'Downloads', blocked_names={'Orbit Workspaces'})
    monkeypatch.setattr(workspaces, 'downloads', legacy)
    workspaces.downloads_for.cache_clear()
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())

    first = workspaces.downloads_for(first_id)
    second = workspaces.downloads_for(second_id)
    assert workspaces.downloads_for(DEFAULT_WORKSPACE_ID) is legacy
    assert first.policy.root != second.policy.root

    asyncio.run(first.execute('create_file', {'path': 'same.txt', 'content': 'first'}))
    asyncio.run(second.execute('create_file', {'path': 'same.txt', 'content': 'second'}))
    assert asyncio.run(first.execute('read_file', {'path': 'same.txt'}))['content'] == 'first'
    assert asyncio.run(second.execute('read_file', {'path': 'same.txt'}))['content'] == 'second'
    with pytest.raises(ValueError, match='reserved'):
        asyncio.run(legacy.execute('read_file', {'path': f'Orbit Workspaces/{first_id}/same.txt'}))
    workspaces.downloads_for.cache_clear()


@pytest.mark.asyncio
async def test_workspace_knowledge_is_isolated_and_agent_accessible(tmp_path, monkeypatch):
    from app.agent.tools import ToolRegistry

    monkeypatch.setattr(workspaces, 'DATA', tmp_path)
    workspaces.knowledge_for.cache_clear()
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    first = workspaces.knowledge_for(first_id)
    second = workspaces.knowledge_for(second_id)
    await first.execute('create_file', {'path': 'notes.txt', 'content': 'first workspace'})
    await second.execute('create_file', {'path': 'notes.txt', 'content': 'second workspace'})

    session = SimpleNamespace(
        files=FileService(tmp_path / 'downloads'),
        knowledge=first,
        mcp=SimpleNamespace(status='closed', tools=[]),
    )
    registry = ToolRegistry(session, 'openai')
    result = json.loads(await registry.execute('knowledge_read', {'path': 'notes.txt'}))
    assert result['content'] == 'first workspace'
    assert (await second.execute('read_file', {'path': 'notes.txt'}))['content'] == 'second workspace'
    assert {'knowledge_list', 'knowledge_read', 'knowledge_create'} <= {item['name'] for item in registry.definitions()}
    workspaces.knowledge_for.cache_clear()

@pytest.mark.asyncio
async def test_parallel_subtasks_overlap_and_keep_input_order(monkeypatch):
    started = 0
    both_started = asyncio.Event()
    closed = []

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            closed.append(self.session_id)

    class Registry:
        def __init__(self, session, provider=None):
            self.session = session

        def definitions(self):
            return []

    async def decide(_provider, _context, messages, _definitions, _emit):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        await asyncio.sleep(0.01 if messages[0]['content'] == 'second task' else 0.03)
        return Decision(messages[0]['content'], [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    args = ParallelArgs.model_validate({'tasks': [
        {'role': 'research', 'task': 'first task'},
        {'role': 'knowledge', 'task': 'second task'},
    ]})
    result = json.loads(await parallel.run_parallel(SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())), args, 'openai'))

    assert [item['result'] for item in result['subtasks']] == ['first task', 'second task']
    assert all(item['status'] == 'completed' for item in result['subtasks'])
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_parallel_failure_is_isolated(monkeypatch):
    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return []

    async def decide(_provider, _context, messages, _definitions, _emit):
        if messages[0]['content'] == 'failing task':
            raise RuntimeError('provider failed')
        return Decision('usable result', [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    args = ParallelArgs.model_validate({'tasks': [
        {'role': 'research', 'task': 'failing task'},
        {'role': 'research', 'task': 'working task'},
    ]})
    result = json.loads(await parallel.run_parallel(SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())), args, 'openai'))

    assert result['subtasks'][0]['status'] == 'failed'
    assert result['subtasks'][1]['status'] == 'completed'
    assert result['subtasks'][1]['result'] == 'usable result'
@pytest.mark.asyncio
async def test_parallel_agent_recovers_from_unavailable_confirmation_tool(monkeypatch):
    calls = 0

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return [
                {'name': 'browser_evaluate', 'description': 'unsafe', 'parameters': {'type': 'object'}},
                {'name': 'browser_snapshot', 'description': 'safe', 'parameters': {'type': 'object', 'additionalProperties': False}},
            ]

        @staticmethod
        def category(_name):
            return 'browser'

        @staticmethod
        def needs_confirmation(_name, _args):
            return False

    async def decide(_provider, _context, messages, definitions, _emit):
        nonlocal calls
        calls += 1
        assert 'browser_evaluate' not in {item['name'] for item in definitions}
        if calls == 1:
            return Decision('', [{'id': 'unsafe', 'name': 'browser_evaluate', 'arguments': {}}])
        assert 'safe read-only alternative' in str(messages[-1]['content'])
        return Decision('recovered result', [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    result = await parallel._subagent(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())),
        parallel.ParallelTask(role='research', task='research fictional product'),
        'openai',
    )
    assert result['status'] == 'completed'
    assert result['result'] == 'recovered result'


@pytest.mark.asyncio
async def test_read_only_search_text_is_not_treated_as_purchase(monkeypatch):
    calls = 0

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = '[ref=e1]'
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return [{'name': 'browser_type', 'description': 'type', 'parameters': {
                'type': 'object', 'properties': {'target': {'type': 'string'}, 'text': {'type': 'string'}},
                'required': ['target', 'text'], 'additionalProperties': False,
            }}]

        @staticmethod
        def category(_name):
            return 'browser'

        @staticmethod
        def needs_confirmation(_name, _args):
            return False

        async def execute(self, _name, _args):
            return 'typed safely'

    async def decide(_provider, _context, _messages, _definitions, _emit):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Decision('', [{'id': 'type', 'name': 'browser_type', 'arguments': {
                'target': 'e1', 'text': 'buy fictional phone specifications',
            }}])
        return Decision('research continued', [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    result = await parallel._subagent(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())),
        parallel.ParallelTask(role='research', task='research fictional product'),
        'openai',
    )
    assert result['status'] == 'completed'
    assert result['result'] == 'research continued'


@pytest.mark.asyncio
async def test_research_agent_pushes_back_on_early_completion(monkeypatch):
    calls = 0

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return [
                {'name': 'browser_initialize', 'description': 'start browser', 'parameters': {
                    'type': 'object', 'additionalProperties': False,
                }},
                {'name': 'file_create_file', 'description': 'create file', 'parameters': {
                    'type': 'object', 'additionalProperties': False,
                }},
            ]

    async def decide(_provider, context, messages, definitions, _emit):
        nonlocal calls
        calls += 1
        assert 'WEB RESEARCH QUALITY STANDARD' in context
        assert 'file_create_file' not in {tool['name'] for tool in definitions}
        if calls > 1:
            assert 'Only 0 independent source page(s)' in messages[-1]['content']
            assert 'research this topic on the web' in messages[-1]['content']
        return Decision('premature summary', [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    result = await parallel._subagent(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())),
        parallel.ParallelTask(role='research', task='research this topic on the web'),
        'openai',
    )

    assert calls == 3
    assert result['research_quality'].startswith('limited:')
    assert result['sources'] == []


@pytest.mark.asyncio
async def test_azure_parallel_agents_serialize_model_calls(monkeypatch):
    active = 0
    peak = 0

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.mcp = SimpleNamespace(status='closed')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return []

    async def decide(_provider, _context, messages, _definitions, _emit):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return Decision(messages[0]['content'], [])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    args = ParallelArgs.model_validate({'tasks': [
        {'role': 'knowledge', 'task': 'first independent task'},
        {'role': 'knowledge', 'task': 'second independent task'},
        {'role': 'knowledge', 'task': 'third independent task'},
    ]})

    result = json.loads(await parallel.run_parallel(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())), args, 'azure',
    ))

    assert result['completed'] == 3
    assert peak == 1


@pytest.mark.asyncio
async def test_rate_limit_is_retried_with_backoff(monkeypatch):
    calls = 0
    delays = []

    class RateLimit(Exception):
        status_code = 429

    async def decide(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimit('too many requests')
        return Decision('recovered', [])

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr(parallel.asyncio, 'sleep', sleep)
    result = await parallel._model_decision('azure', 'context', [], [], lambda _event: None)

    assert result.text == 'recovered'
    assert calls == 2
    assert delays == [5]


@pytest.mark.asyncio
async def test_research_agent_tracks_independent_source_pages(monkeypatch):
    urls = iter([
        'https://example.gov/official-record',
        'https://news.example.org/profile',
        'https://archive.example.edu/timeline',
    ])
    decisions = iter([
        Decision('', [{'id': '1', 'name': 'browser_navigate', 'arguments': {'url': 'https://example.gov/official-record'}}]),
        Decision('', [{'id': '2', 'name': 'browser_navigate', 'arguments': {'url': 'https://news.example.org/profile'}}]),
        Decision('', [{'id': '3', 'name': 'browser_navigate', 'arguments': {'url': 'https://archive.example.edu/timeline'}}]),
        Decision('cross-checked findings with [1], [2], and [3]', []),
    ])

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = ''
            self.url = ''
            self.mcp = SimpleNamespace(status='connected')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return [{'name': 'browser_navigate', 'description': 'navigate', 'parameters': {
                'type': 'object',
                'properties': {'url': {'type': 'string'}},
                'required': ['url'],
                'additionalProperties': False,
            }}]

        @staticmethod
        def category(_name):
            return 'browser'

        @staticmethod
        def needs_confirmation(_name, _args):
            return False

        async def execute(self, _name, _args):
            return 'navigated'

    async def observation(session, screenshot=True):
        session.url = next(urls)
        session.snapshot = 'source page'
        return session.snapshot

    async def decide(*_args):
        return next(decisions)

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'observe', observation)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    result = await parallel._subagent(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())),
        parallel.ParallelTask(role='research', task='research this topic using reliable sources'),
        'openai',
    )

    assert result['research_quality'] == 'source-verified'
    assert len(result['sources']) == 3
    assert not parallel._is_evidence_url('https://www.google.com/search?q=topic')


@pytest.mark.asyncio
async def test_research_step_limit_returns_best_available_findings(monkeypatch):
    calls = 0
    screenshot_values = []

    class Session:
        def __init__(self, session_id, workspace_id):
            self.session_id, self.workspace_id = session_id, workspace_id
            self.snapshot = 'source evidence'
            self.url = 'https://example.org/source'
            self.mcp = SimpleNamespace(status='connected')

        async def close(self):
            return None

    class Registry:
        def __init__(self, session, provider=None):
            pass

        def definitions(self):
            return [{'name': 'browser_navigate', 'description': 'navigate', 'parameters': {
                'type': 'object',
                'properties': {'url': {'type': 'string'}},
                'required': ['url'],
                'additionalProperties': False,
            }}]

        @staticmethod
        def category(_name):
            return 'browser'

        @staticmethod
        def needs_confirmation(_name, _args):
            return False

        async def execute(self, _name, _args):
            return 'evidence gathered'

    async def observation(session, screenshot=True):
        screenshot_values.append(screenshot)
        return session.snapshot

    async def decide(_provider, context, _messages, definitions, _emit):
        nonlocal calls
        calls += 1
        if not definitions:
            assert 'browsing step budget is exhausted' in context
            return Decision('Best available findings from the gathered source.', [])
        return Decision('', [{'id': str(calls), 'name': 'browser_navigate', 'arguments': {
            'url': 'https://example.org/source',
        }}])

    monkeypatch.setattr(parallel, 'BrowserSession', Session)
    monkeypatch.setattr(parallel, 'observe', observation)
    monkeypatch.setattr(parallel, 'decide', decide)
    monkeypatch.setattr('app.agent.tools.ToolRegistry', Registry)
    result = await parallel._subagent(
        SimpleNamespace(session_id='parent', workspace_id=str(uuid.uuid4())),
        parallel.ParallelTask(role='research', task='research a difficult topic'),
        'openai',
    )

    assert calls == parallel.RESEARCH_MAX_STEPS + 1
    assert result['status'] == 'completed'
    assert result['step_limit_reached'] is True
    assert result['result'].startswith('Best available findings')
    assert result['research_quality'].startswith('limited:')
    assert screenshot_values and not any(screenshot_values)

