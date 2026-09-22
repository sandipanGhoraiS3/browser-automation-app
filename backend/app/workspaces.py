from functools import lru_cache
from pathlib import Path
import shutil
from uuid import UUID
from app.config import DATA
from app.database.store import DEFAULT_WORKSPACE_ID
from app.file_agent.service import FileService, downloads, files
from app.skills.registry import SkillRegistry, registry


def validated_workspace_id(workspace_id: str) -> str:
    return str(UUID(str(workspace_id)))


def workspace_root(workspace_id: str) -> Path:
    workspace_id = validated_workspace_id(workspace_id)
    root = DATA / 'workspaces' / workspace_id
    root.mkdir(parents=True, exist_ok=True)
    (root / 'knowledge').mkdir(exist_ok=True)
    return root


@lru_cache(maxsize=128)
def files_for(workspace_id: str) -> FileService:
    workspace_id = validated_workspace_id(workspace_id)
    return files if workspace_id == DEFAULT_WORKSPACE_ID else FileService(workspace_root(workspace_id) / 'files')


@lru_cache(maxsize=128)
def skills_for(workspace_id: str) -> SkillRegistry:
    workspace_id = validated_workspace_id(workspace_id)
    return registry if workspace_id == DEFAULT_WORKSPACE_ID else SkillRegistry(workspace_root(workspace_id) / 'skills')


@lru_cache(maxsize=128)
def knowledge_for(workspace_id: str) -> FileService:
    workspace_id = validated_workspace_id(workspace_id)
    return FileService(workspace_root(workspace_id) / 'knowledge')


@lru_cache(maxsize=128)
def downloads_for(workspace_id: str) -> FileService:
    """Keep legacy Downloads behavior for Default; isolate additional workspaces."""
    workspace_id = validated_workspace_id(workspace_id)
    if workspace_id == DEFAULT_WORKSPACE_ID:
        return downloads
    return FileService(downloads.policy.root / 'Orbit Workspaces' / workspace_id)


def _workspace_child(base: Path, workspace_id: str) -> Path:
    workspace_id = validated_workspace_id(workspace_id)
    base = base.resolve()
    target = base / workspace_id
    resolved = target.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError('Workspace storage resolved outside its managed directory.')
    return target


def remove_workspace_storage(workspace_id: str):
    workspace_id = validated_workspace_id(workspace_id)
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise ValueError('The default workspace cannot be deleted.')
    targets = [
        _workspace_child(DATA / 'workspaces', workspace_id),
        _workspace_child(downloads.policy.root / 'Orbit Workspaces', workspace_id),
    ]
    for target in targets:
        if target.exists():
            if target.is_symlink():
                raise ValueError('Refusing to delete linked workspace storage.')
            shutil.rmtree(target)
    files_for.cache_clear()
    skills_for.cache_clear()
    knowledge_for.cache_clear()
    downloads_for.cache_clear()




