import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.database.store import store, DEFAULT_WORKSPACE_ID
from app.skills.models import CreateSkill, EditSkill
from app.workspaces import files_for, skills_for, workspace_root, remove_workspace_storage
from app.rag.service import rag_service

router = APIRouter(prefix='/api')

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

def services(workspace_id):
    workspace_id = str(workspace_id)
    if not store.workspace(workspace_id):
        raise HTTPException(404, 'Workspace not found')
    return files_for(workspace_id), skills_for(workspace_id)

@router.get('/workspaces')
async def list_workspaces():
    return store.workspaces()

@router.post('/workspaces')
async def create_workspace(body: WorkspaceCreate):
    workspace = store.create_workspace(body.name)
    workspace_root(workspace['id'])
    return workspace

@router.delete('/workspaces/{workspace_id}')
async def delete_workspace(workspace_id: str):
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise HTTPException(409, 'The default workspace cannot be deleted.')
    if not store.workspace(workspace_id):
        raise HTTPException(404, 'Workspace not found')
    from app.sessions.manager import manager
    sessions = [
        (session_id, session) for session_id, session in manager.sessions.items()
        if session.workspace_id == workspace_id
    ]
    try:
        for session_id, session in sessions:
            await session.close()
            manager.sessions.pop(session_id, None)
        if rag_service.configured:
            await rag_service.delete_workspace(workspace_id)
        await asyncio.to_thread(remove_workspace_storage, workspace_id)
        conversations = len(store.conversations(workspace_id))
        store.delete_workspace(workspace_id)
        return {'ok': True, 'deleted_conversations': conversations}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Workspace knowledge cleanup failed; the workspace was retained so deletion can be retried safely.') from exc

@router.get('/files/status')
async def file_status(workspace_id: str = DEFAULT_WORKSPACE_ID):
    workspace_files, _ = services(workspace_id)
    return {'status': 'available', 'workspace': str(workspace_files.policy.root), 'external_folders': [], 'max_bytes': workspace_files.max_bytes}

@router.get('/files')
async def list_files(path: str = '.', workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        workspace_files, _ = services(workspace_id)
        return await workspace_files.execute('list_directory', {'path': path})
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/skills')
async def list_skills(workspace_id: str = DEFAULT_WORKSPACE_ID):
    _, workspace_skills = services(workspace_id)
    return await asyncio.to_thread(workspace_skills.discover)

@router.get('/skills/{name}')
async def get_skill(name: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        _, workspace_skills = services(workspace_id)
        return await asyncio.to_thread(workspace_skills.load, name)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post('/skills')
async def create_skill(body: CreateSkill, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        _, workspace_skills = services(workspace_id)
        return await asyncio.to_thread(workspace_skills.create, body)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc

@router.put('/skills/{name}')
async def edit_skill(name: str, body: EditSkill, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        _, workspace_skills = services(workspace_id)
        return await asyncio.to_thread(workspace_skills.edit, name, body.markdown, body.revision)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc

@router.delete('/skills/{name}')
async def delete_skill(name: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        _, workspace_skills = services(workspace_id)
        await asyncio.to_thread(workspace_skills.delete, name)
        return {'ok': True}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
