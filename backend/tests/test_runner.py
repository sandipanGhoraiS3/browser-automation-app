import asyncio
import pytest
from types import SimpleNamespace
from app.agent import runner, tools
from app.agent.providers import Decision
from app.database.store import Store
from app.file_agent.service import FileService
from app.sessions.manager import BrowserSession

class FakeMCP:
    def __init__(self):
        self.status = 'closed'
        self.tools = []
        self.start_calls = 0
        self.call_names = []

    async def start(self):
        self.start_calls += 1
        self.status = 'connected'
        self.tools = [SimpleNamespace(name='browser_navigate', description='Navigate to a URL', inputSchema={
            'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url'], 'additionalProperties': False})]

    async def call(self, name, args):
        self.call_names.append(name)
        return SimpleNamespace(isError=False, content=[SimpleNamespace(type='text', text='Navigated')])

@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    db = Store(tmp_path / 'runs.sqlite')
    cid = db.create()['id']
    db.message(cid, 'user', 'Run skill: test_skill')
    session = BrowserSession(cid)
    session.mcp = FakeMCP()
    monkeypatch.setattr(runner, 'store', db)
    session.files = FileService(tmp_path / 'downloads')
    async def observation(session, screenshot=True):
        return 'about:blank'
    monkeypatch.setattr(runner, 'observe', observation)
    return session, db, tmp_path

@pytest.mark.asyncio
async def test_skill_runs_through_unified_file_tools(setup_run, monkeypatch):
    session, db, path = setup_run
    choices = iter([
        Decision('', [{'id': 'a', 'name': 'file_create_folder', 'arguments': {'path': 'checks'}}]),
        Decision('', [{'id': 'b', 'name': 'file_create_file', 'arguments': {'path': 'checks/test.txt', 'content': 'Workspace check completed.'}}]),
        Decision('', [{'id': 'c', 'name': 'file_read_file', 'arguments': {'path': 'checks/test.txt'}}]),
        Decision('Saved checks/test.txt and verified the contents.', []),
    ])
    async def model(provider, system, *args):
        assert 'Workspace Check' in system
        return next(choices)
    monkeypatch.setattr(runner, 'decide', model)
    await runner.run(session, 'Run skill: test_skill', 'azure')
    generated = path / 'downloads/checks/test.txt'
    assert generated.exists(), session.activity
    assert generated.read_text() == 'Workspace check completed.'
    assert db.rows('SELECT status FROM agent_runs')[0]['status'] == 'completed'
    assert {'file', 'skill'} <= {a.get('category') for a in session.activity}
    assert session.mcp.status == 'closed'
    assert session.mcp.start_calls == 0

@pytest.mark.asyncio
async def test_cancellation_during_model_preserves_session(setup_run, monkeypatch):
    session, db, _ = setup_run
    started = asyncio.Event()
    async def model(*args):
        started.set()
        await asyncio.sleep(100)
    monkeypatch.setattr(runner, 'decide', model)
    session.task = asyncio.create_task(runner.run(session, '/run test_skill', 'azure'))
    await started.wait()
    await session.cancel()
    assert db.rows('SELECT status FROM agent_runs')[0]['status'] == 'cancelled'
    assert session.mcp.status == 'closed'
    assert session.mcp.start_calls == 0


@pytest.mark.asyncio
async def test_normal_conversation_does_not_start_or_observe_browser(setup_run, monkeypatch):
    session, _, _ = setup_run

    async def no_observation(*args, **kwargs):
        raise AssertionError('Browser observation should not run for normal conversation.')

    async def model(*args):
        return Decision('Hello! How can I help?', [])

    monkeypatch.setattr(runner, 'observe', no_observation)
    monkeypatch.setattr(runner, 'decide', model)
    await runner.run(session, 'Hello', 'azure')
    assert session.mcp.start_calls == 0
    assert session.mcp.status == 'closed'


@pytest.mark.asyncio
async def test_browser_initializes_only_after_browser_tool_selection(setup_run, monkeypatch):
    session, _, _ = setup_run
    choices = iter([
        Decision('', [{'id': 'a', 'name': 'browser_initialize', 'arguments': {}}]),
        Decision('', [{'id': 'b', 'name': 'browser_navigate', 'arguments': {'url': 'https://example.com'}}]),
        Decision('Website opened.', []),
    ])

    async def model(provider, system, messages, definitions, emit):
        decision = next(choices)
        names = {tool['name'] for tool in definitions}
        if decision.calls and decision.calls[0]['name'] == 'browser_initialize':
            assert 'browser_navigate' not in names
        if decision.calls and decision.calls[0]['name'] == 'browser_navigate':
            assert 'browser_navigate' in names
        return decision

    monkeypatch.setattr(runner, 'decide', model)
    await runner.run(session, 'Open https://example.com', 'azure')
    assert session.mcp.start_calls == 1
    assert session.mcp.call_names == ['browser_navigate']
    assert session.mcp.status == 'connected'


@pytest.mark.asyncio
async def test_selected_knowledge_domain_does_not_attach_sources_to_browser_task(setup_run, monkeypatch):
    session, db, _ = setup_run
    choices = iter([
        Decision('', [{'id': 'a', 'name': 'browser_initialize', 'arguments': {}}]),
        Decision('', [{'id': 'b', 'name': 'browser_navigate', 'arguments': {'url': 'https://example.com'}}]),
        Decision('Website opened.', []),
    ])

    async def model(*args):
        return next(choices)

    monkeypatch.setattr(runner, 'decide', model)
    await runner.run(
        session, 'Open https://example.com', 'azure',
        use_knowledge=True, knowledge_domain_id='selected-domain',
    )
    response = db.conversation(session.session_id)['messages'][-1]
    assert response['content'] == 'Website opened.'
    assert response.get('sources') is None
    assert response.get('retrieval') is None

@pytest.mark.asyncio
async def test_delete_confirmation_denial(setup_run, monkeypatch):
    session, db, path = setup_run
    target = path / 'downloads/keep.txt'
    target.write_text('keep')
    choices = iter([Decision('', [{'id': 'a', 'name': 'file_delete_file', 'arguments': {'path': 'keep.txt'}}]), Decision('Deletion cancelled.', [])])
    async def model(*args):
        return next(choices)
    monkeypatch.setattr(runner, 'decide', model)
    session.task = asyncio.create_task(runner.run(session, 'Delete keep.txt', 'azure'))
    for _ in range(100):
        if session.confirmation:
            break
        await asyncio.sleep(.01)
    assert session.confirmation
    session.confirmation.set_result(False)
    await session.task
    assert target.exists()
    assert db.rows('SELECT status FROM tool_calls')[0]['status'] == 'failed'

