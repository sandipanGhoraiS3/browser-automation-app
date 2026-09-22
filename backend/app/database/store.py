import sqlite3
import uuid
import json
from datetime import datetime, timezone
from app.config import DATA
from app.services.security import redact

DEFAULT_WORKSPACE_ID = '00000000-0000-0000-0000-000000000001'

def now():
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, path=DATA / 'history.sqlite3'):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT);
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,role TEXT,content TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS agent_runs(id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,status TEXT,started_at TEXT,completed_at TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS tool_calls(id TEXT PRIMARY KEY,agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,tool_name TEXT,status TEXT,started_at TEXT,completed_at TEXT,error TEXT);
        ''')
        self.db.execute('INSERT OR IGNORE INTO workspaces VALUES(?,?,?)', (DEFAULT_WORKSPACE_ID, 'Default Workspace', now()))
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(conversations)')}
        if 'workspace_id' not in columns:
            self.db.execute('ALTER TABLE conversations ADD COLUMN workspace_id TEXT')
        message_columns = {row['name'] for row in self.db.execute('PRAGMA table_info(messages)')}
        if 'metadata' not in message_columns:
            self.db.execute('ALTER TABLE messages ADD COLUMN metadata TEXT')
        self.db.execute('UPDATE conversations SET workspace_id=? WHERE workspace_id IS NULL', (DEFAULT_WORKSPACE_ID,))
        self.db.execute('CREATE INDEX IF NOT EXISTS conversations_workspace ON conversations(workspace_id,updated_at)')
        self.db.execute("UPDATE agent_runs SET status='interrupted',completed_at=? WHERE status='running'", (now(),))
        self.db.commit()

    def execute(self, sql, args=()):
        result = self.db.execute(sql, args)
        self.db.commit()
        return result

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def workspaces(self):
        return self.rows('SELECT * FROM workspaces ORDER BY created_at,id')

    def workspace(self, workspace_id):
        rows = self.rows('SELECT * FROM workspaces WHERE id=?', (workspace_id,))
        return rows[0] if rows else None

    def create_workspace(self, name):
        workspace_id = str(uuid.uuid4())
        self.execute('INSERT INTO workspaces VALUES(?,?,?)', (workspace_id, redact(name), now()))
        return self.workspace(workspace_id)

    def delete_workspace(self, workspace_id):
        if workspace_id == DEFAULT_WORKSPACE_ID:
            raise ValueError('The default workspace cannot be deleted.')
        if not self.workspace(workspace_id):
            return False
        try:
            self.db.execute('BEGIN')
            self.db.execute('DELETE FROM conversations WHERE workspace_id=?', (workspace_id,))
            deleted = self.db.execute('DELETE FROM workspaces WHERE id=?', (workspace_id,)).rowcount
            self.db.commit()
            return bool(deleted)
        except Exception:
            self.db.rollback()
            raise

    def create(self, title='New conversation', workspace_id=DEFAULT_WORKSPACE_ID):
        if not self.workspace(workspace_id):
            raise ValueError('Workspace not found.')
        cid = str(uuid.uuid4())
        self.execute('INSERT INTO conversations(id,title,created_at,updated_at,workspace_id) VALUES(?,?,?,?,?)', (cid, redact(title), now(), now(), workspace_id))
        return self.conversation(cid, workspace_id)

    def conversation(self, cid, workspace_id=None):
        sql, args = ('SELECT * FROM conversations WHERE id=?', (cid,)) if workspace_id is None else ('SELECT * FROM conversations WHERE id=? AND workspace_id=?', (cid, workspace_id))
        rows = self.rows(sql, args)
        if not rows:
            return None
        messages = self.rows('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at', (cid,))
        for message in messages:
            try:
                metadata = json.loads(message.pop('metadata') or '{}')
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            message.update(metadata)
        return {**rows[0], 'messages': messages}

    def message(self, cid, role, content, metadata=None):
        msg = dict(id=str(uuid.uuid4()), conversation_id=cid, role=role, content=redact(content), created_at=now())
        safe_metadata = json.dumps(metadata or {}, ensure_ascii=False)
        self.execute(
            'INSERT INTO messages(id,conversation_id,role,content,created_at,metadata) VALUES(?,?,?,?,?,?)',
            (*msg.values(), safe_metadata),
        )
        self.execute('UPDATE conversations SET updated_at=? WHERE id=?', (now(), cid))
        return {**msg, **(metadata or {})}

    def conversations(self, workspace_id=DEFAULT_WORKSPACE_ID):
        return self.rows('SELECT * FROM conversations WHERE workspace_id=? ORDER BY updated_at DESC', (workspace_id,))

store = Store()
