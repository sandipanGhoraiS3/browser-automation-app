import asyncio
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.database.store import Store
from app.agent.runner import valid_refs, CLOSE, confirmation
from app.agent.providers import Decision, append_result
from app.sessions.manager import BrowserSession
from app.services.security import redact
from app.main import app

def test_persistence_redaction_and_cascade(tmp_path):
    db = Store(tmp_path / 'test.sqlite')
    cid = db.create()['id']
    db.message(cid, 'user', 'password=hunter2 api_key=secretvalue')
    assert 'hunter2' not in db.conversation(cid)['messages'][0]['content']
    reopened = Store(tmp_path / 'test.sqlite')
    assert len(reopened.conversation(cid)['messages']) == 1
    db.execute('DELETE FROM conversations WHERE id=?', (cid,))
    assert not db.rows('SELECT * FROM messages')

def test_stale_refs_rejected():
    valid_refs({'ref': 'e3'}, '- button "Go" [ref=e3]')
    with pytest.raises(ValueError):
        valid_refs({'fields': [{'ref': 'e2'}]}, '- button "Go" [ref=e3]')
    with pytest.raises(ValueError):
        valid_refs({'startRef': 'e1', 'endRef': 'e3'}, '[ref=e3]')

def test_close_requires_explicit_command():
    assert CLOSE.fullmatch('close the browser')
    assert CLOSE.fullmatch('Please close browser.')
    assert not CLOSE.fullmatch('Search for how to close browser')

def test_provider_tool_protocols():
    decision = Decision('Opening', [{'id': 'call-1', 'name': 'browser_navigate', 'arguments': {'url': 'https://example.com'}}])
    messages = []
    append_result(messages, decision, 'OK', 'azure')
    assert messages[1]['tool_call_id'] == 'call-1'
    messages = []
    append_result(messages, decision, 'OK', 'anthropic')
    assert messages[1]['content'][0]['tool_use_id'] == 'call-1'


@pytest.mark.asyncio
async def test_provider_recovers_from_unsupported_temperature(monkeypatch):
    from app.agent import providers

    requests = []
    expected_stream = object()

    class UnsupportedTemperature(Exception):
        status_code = 400

    class Completions:
        async def create(self, **request):
            requests.append(request)
            if len(requests) == 1:
                raise UnsupportedTemperature('temperature is an unsupported value')
            return expected_stream

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(providers, '_NO_TEMPERATURE_MODELS', set())
    request = {
        'model': 'new-model', 'messages': [],
        'temperature': 0.0, 'stream': True,
    }
    model_key = ('azure', 'new-model')

    result = await providers._create_chat_stream(client, request, model_key)
    assert result is expected_stream
    assert 'temperature' in requests[0]
    assert 'temperature' not in requests[1]

    result = await providers._create_chat_stream(client, request, model_key)
    assert result is expected_stream
    assert 'temperature' not in requests[2]


@pytest.mark.asyncio
async def test_confirmation_is_bound_to_pending_future():
    session = BrowserSession('test-confirm')
    task = asyncio.create_task(confirmation(session, 'Send message'))
    await asyncio.sleep(0)
    assert session.pending_confirmation['description'] == 'Send message'
    session.confirmation.set_result(False)
    assert await task is False
    assert session.pending_confirmation is None

@pytest.mark.asyncio
async def test_cancel_preserves_browser():
    session = BrowserSession('test-cancel')
    session.mcp.status = 'connected'
    session.task = asyncio.create_task(asyncio.sleep(100))
    await session.cancel()
    assert session.task.cancelled()
    assert session.mcp.status == 'connected'

def test_api_validation_and_local_origin():
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.post('/api/conversations', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/conversations/../../secrets').status_code == 404
        created = client.post('/api/conversations', json={'title': 'Test'}).json()
        cid = created['id']
        session = client.post('/api/sessions', json={'conversation_id': cid}).json()
        assert session['browser']['status'] == 'closed'
        assert client.patch('/api/conversations/' + cid, json={'title': 'Renamed'}).json()['title'] == 'Renamed'
        assert client.post('/api/chat', json={'session_id': cid, 'message': ' ', 'provider': 'azure'}).status_code == 422
        assert client.delete('/api/conversations/' + cid).status_code == 200
        assert client.get('/api/conversations/' + cid).status_code == 404

def test_secret_patterns():
    assert 'abc123' not in redact('token=abc123')
@pytest.mark.asyncio
async def test_observe_keeps_snapshot_when_preview_capture_fails(monkeypatch):
    from app.browser import state

    class MCP:
        async def call(self, name, _args):
            text = 'Page URL: https://example.com' if name == 'browser_snapshot' else '### Result\n- 0: current'
            return SimpleNamespace(isError=False, content=[SimpleNamespace(type='text', text=text)])

    events = []
    session = SimpleNamespace(
        mcp=MCP(), snapshot='', url='', tabs='', downloads={}, screenshot=0,
        emit=lambda event: _append_event(events, event),
        browser_state=lambda: {'status': 'connected', 'url': 'https://example.com', 'tabs': '', 'screenshot': 0},
    )

    async def fail_capture(*_args, **_kwargs):
        raise ValueError('preview unavailable')

    async def no_downloads(*_args, **_kwargs):
        return []

    monkeypatch.setattr(state, 'capture', fail_capture)
    monkeypatch.setattr(state, 'detect_downloads', no_downloads)
    result = await state.observe(session, screenshot=True)
    assert result.startswith('Page URL:')
    assert session.snapshot == result
    assert events and events[-1]['type'] == 'browser'


async def _append_event(events, event):
    events.append(event)
def test_compact_messages_keeps_current_request_and_complete_tool_pairs():
    from app.agent.providers import compact_messages

    messages = [{'role': 'user', 'content': 'current research request'}]
    for index in range(5):
        messages.extend([
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': str(index)}]},
            {'role': 'tool', 'tool_call_id': str(index), 'content': str(index) * 20000},
        ])
    compacted = compact_messages(messages, max_chars=45000)
    assert compacted[0]['content'] == 'current research request'
    assert compacted[-1]['tool_call_id'] == '4'
    assert len(compacted[1:]) % 2 == 0
    for index in range(1, len(compacted), 2):
        assert compacted[index]['role'] == 'assistant'
        assert compacted[index + 1]['role'] == 'tool'

