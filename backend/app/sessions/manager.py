import asyncio
import time
from app.mcp.process import MCPProcess
from app.services.security import redact
from app.database.store import DEFAULT_WORKSPACE_ID
from app.workspaces import downloads_for, knowledge_for, skills_for

class BrowserSession:
    def __init__(self, session_id, workspace_id=DEFAULT_WORKSPACE_ID):
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.skills = skills_for(workspace_id)
        self.files = downloads_for(workspace_id)
        self.knowledge = knowledge_for(workspace_id)
        self.mcp = MCPProcess(session_id, workspace_id)
        self.created_at = self.last_activity = time.time()
        self.task = None
        self.listeners = set()
        self.snapshot = ''
        self.url = ''
        self.tabs = ''
        self.screenshot = 0
        self.screenshots = {}
        self.capture_lock = asyncio.Lock()
        self.downloads = {}
        self.active_skills = {}
        self.confirmation = None
        self.pending_confirmation = None
        self.activity = []
        self.partial = ''
        self.status = 'idle'
        self.use_knowledge = None
        self.knowledge_domain_id = None
        self.rag_sources = []
        self.rag_debug = None

    async def emit(self, event):
        if event['type'] == 'delta':
            event['text'] = redact(event['text'])
            self.partial += event['text']
        elif event['type'] == 'activity':
            self.activity = [a for a in self.activity if a['id'] != event['id']] + [event]
        elif event['type'] == 'status':
            self.status = event['status']
        elif event['type'] == 'message':
            self.partial = ''
        for queue in list(self.listeners):
            if queue.full():
                # Slow clients receive a full state on reconnect instead of growing memory forever.
                self.listeners.discard(queue)
                continue
            queue.put_nowait(event)

    def browser_state(self):
        return {'status': self.mcp.status, 'url': redact(self.url), 'tabs': redact(self.tabs), 'screenshot': self.screenshot}

    def state(self):
        return {'id': self.session_id, 'status': self.status, 'browser': self.browser_state(), 'activity': self.activity, 'partial': self.partial, 'confirmation': self.pending_confirmation}

    async def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def close(self):
        await self.cancel()
        await self.mcp.stop()
        self.url, self.tabs, self.screenshot = '', '', 0
        await self.emit({'type': 'browser', **self.browser_state()})

class SessionManager:
    def __init__(self):
        self.sessions = {}

    def get(self, cid, workspace_id=DEFAULT_WORKSPACE_ID):
        if cid not in self.sessions:
            self.sessions[cid] = BrowserSession(cid, workspace_id)
        elif self.sessions[cid].workspace_id != workspace_id:
            raise ValueError('Conversation belongs to another workspace.')
        return self.sessions[cid]

    async def cleanup(self, timeout):
        while True:
            await asyncio.sleep(30)
            for session in list(self.sessions.values()):
                if (not session.task or session.task.done()) and time.time() - session.last_activity > timeout and session.mcp.status == 'connected':
                    await session.close()

    async def shutdown(self):
        await asyncio.gather(*(s.close() for s in self.sessions.values()))

manager = SessionManager()



