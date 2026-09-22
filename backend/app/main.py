import asyncio
import contextlib
import shutil
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from app.config import settings, ROOT
from app.database.store import store, now
from app.database.store import DEFAULT_WORKSPACE_ID
from app.sessions.manager import manager
from app.agent.runner import run
from app.agent.providers import configured
from app.services.security import redact
from app.browser.state import capture
from app.api.workspace import router as workspace_router
from app.api.knowledge import router as knowledge_router
from app.rag.service import rag_service

ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173']

@asynccontextmanager
async def lifespan(app):
    cleanup = asyncio.create_task(manager.cleanup(settings.session_idle_timeout))
    recovery = asyncio.create_task(rag_service.recover_interrupted())
    yield
    cleanup.cancel()
    recovery.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup
    with contextlib.suppress(asyncio.CancelledError):
        await recovery
    await manager.shutdown()
    await rag_service.shutdown()

app = FastAPI(title='Orbit Browser Agent', lifespan=lifespan)
app.include_router(workspace_router)
app.include_router(knowledge_router)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Content-Type'])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])

@app.middleware('http')
async def local_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in ORIGINS:
        return JSONResponse({'detail': 'Untrusted origin'}, status_code=403)
    return await call_next(request)

class Title(BaseModel):
    title: str = Field(default='New conversation', min_length=1, max_length=120)

class SessionInput(BaseModel):
    conversation_id: UUID
    workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)

class ConversationCreate(Title):
    workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)

class ChatInput(BaseModel):
    session_id: UUID
    workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)
    message: str = Field(min_length=1, max_length=20000)
    provider: Literal['openai', 'azure', 'anthropic'] = 'openai'
    use_knowledge: bool | None = None
    knowledge_domain_id: UUID | None = None

class StopInput(BaseModel):
    session_id: UUID
    workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)

def session_for(cid, workspace_id=None):
    cid = str(cid)
    conversation = store.conversation(cid, str(workspace_id)) if workspace_id is not None else store.conversation(cid)
    if not conversation:
        raise HTTPException(404, 'Conversation not found')
    try:
        return manager.get(cid, conversation['workspace_id'])
    except ValueError as exc:
        raise HTTPException(404, 'Conversation not found') from exc

@app.get('/api/health')
async def health():
    installed = (ROOT / 'node_modules/@playwright/mcp/cli.js').exists()
    return {'status': 'ok', 'browser_service': 'available' if shutil.which('node') else 'unavailable', 'mcp': 'available' if installed else 'not_installed', 'providers': {p: configured(p) for p in ['openai', 'azure', 'anthropic']}, 'models': {'openai': settings.openai_model, 'azure': settings.azure_openai_deployment, 'anthropic': settings.anthropic_model}, 'max_steps': settings.max_agent_steps, 'idle_timeout': settings.session_idle_timeout}

@app.post('/api/conversations')
async def create_conversation(body: ConversationCreate):
    try:
        return store.create(body.title, str(body.workspace_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

@app.get('/api/conversations')
async def conversations(workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    return store.conversations(str(workspace_id))

@app.get('/api/conversations/{cid}')
async def conversation(cid: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    session_for(cid, workspace_id)
    return store.conversation(str(cid), str(workspace_id))

@app.patch('/api/conversations/{cid}')
async def rename(cid: UUID, body: Title, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    session_for(cid, workspace_id)
    store.execute('UPDATE conversations SET title=?,updated_at=? WHERE id=?', (redact(body.title), now(), str(cid)))
    return store.conversation(str(cid), str(workspace_id))

@app.delete('/api/conversations/{cid}')
async def delete_conversation(cid: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    session = session_for(cid, workspace_id)
    await session.close()
    manager.sessions.pop(str(cid), None)
    store.execute('DELETE FROM conversations WHERE id=?', (str(cid),))
    # Remove only generated artifacts for the validated UUID inside the session root.
    await asyncio.to_thread(shutil.rmtree, session.mcp.directory, True)
    return {'ok': True}

@app.post('/api/sessions')
async def create_session(body: SessionInput):
    session = session_for(body.conversation_id, body.workspace_id)
    return session.state()

@app.get('/api/sessions/{sid}')
async def get_session(sid: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    return session_for(sid, workspace_id).state()

@app.delete('/api/sessions/{sid}')
async def close_session(sid: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    session = session_for(sid, workspace_id)
    await session.close()
    return session.state()

@app.post('/api/chat')
async def chat(body: ChatInput):
    session = session_for(body.session_id, body.workspace_id)
    if session.task and not session.task.done():
        raise HTTPException(409, 'This conversation already has a running task.')
    if not body.message.strip():
        raise HTTPException(422, 'Message cannot be blank.')
    # Redact BEFORE persistence or model history. Enter credentials directly in the browser.
    message = store.message(session.session_id, 'user', body.message)
    if store.conversation(session.session_id, session.workspace_id)['title'] == 'New conversation':
        store.execute('UPDATE conversations SET title=? WHERE id=?', (redact(body.message[:60]), session.session_id))
    await session.emit({'type': 'message', 'message': message})
    session.task = asyncio.create_task(run(
        session, body.message, body.provider, body.use_knowledge,
        str(body.knowledge_domain_id) if body.knowledge_domain_id else None,
    ))
    return {'accepted': True}

@app.post('/api/chat/stop')
async def stop(body: StopInput):
    await session_for(body.session_id, body.workspace_id).cancel()
    return {'ok': True}

@app.get('/api/browser/status')
async def browser_status(session_id: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    return session_for(session_id, workspace_id).browser_state()

@app.get('/api/browser/tabs')
async def tabs(session_id: UUID, workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    return {'tabs': session_for(session_id, workspace_id).tabs}

@app.get('/api/browser/screenshot')
async def screenshot(session_id: UUID, mode: Literal['viewport', 'full_page'] = 'viewport', workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)):
    session = session_for(session_id, workspace_id)
    path = session.mcp.directory / 'screenshots' / ('latest.png' if mode == 'viewport' else 'full_page.png')
    if (not session.screenshot if mode == 'viewport' else not session.screenshots.get(mode)) or not path.exists():
        raise HTTPException(404, 'No screenshot yet')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store'})

class CaptureInput(BaseModel):
    session_id: UUID
    workspace_id: UUID = UUID(DEFAULT_WORKSPACE_ID)
    mode: Literal['viewport', 'full_page'] = 'viewport'

@app.post('/api/browser/screenshot')
async def capture_screenshot(body: CaptureInput):
    session = session_for(body.session_id, body.workspace_id)
    if session.mcp.status != 'connected':
        raise HTTPException(409, 'Open a browser session before taking a screenshot.')
    try:
        result = await capture(session, body.mode)
        return {'mode': result['mode'], 'version': result['version']}
    except Exception as exc:
        raise HTTPException(503, 'Unable to capture screenshot. Check the browser and retry.') from exc

@app.websocket('/ws/{sid}')
async def websocket(ws: WebSocket, sid: UUID):
    workspace_id = ws.query_params.get('workspace_id', DEFAULT_WORKSPACE_ID)
    if ws.headers.get('origin') not in ORIGINS or not store.conversation(str(sid), workspace_id):
        await ws.close(code=1008)
        return
    session = session_for(sid, workspace_id)
    await ws.accept()
    queue = asyncio.Queue(maxsize=1000)
    session.listeners.add(queue)
    await ws.send_json({'type': 'state', **session.state(), 'messages': store.conversation(str(sid), workspace_id)['messages']})
    async def sender():
        while True:
            await ws.send_json(await queue.get())
    writer = asyncio.create_task(sender())
    try:
        while True:
            data = await ws.receive_json()
            if data.get('type') == 'stop':
                await session.cancel()
            elif data.get('type') == 'confirm' and session.confirmation and not session.confirmation.done() and data.get('id') == session.pending_confirmation['id']:
                session.confirmation.set_result(data.get('approved') is True)
    except WebSocketDisconnect:
        pass
    finally:
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer
        session.listeners.discard(queue)
# Backward-compatible ASGI target for launch configurations using app.main:main.
main = app

