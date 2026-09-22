import re
import uuid
from pathlib import Path
from app.file_agent.service import downloads


def _available_name(name: str, service=downloads) -> str:
    safe = Path(name.replace('\\', '/')).name
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe).rstrip(' .') or 'download'
    try:
        service.policy.resolve(safe)
    except ValueError:
        safe = 'download' + Path(safe).suffix
    return safe

async def detect_downloads(session, result_text):
    """Trust only completed-download records emitted by MCP and confined local artifacts."""
    added = []
    service = getattr(session, 'files', downloads)
    for match in re.finditer(r'^- Downloaded file (.+?) to "(.+?)"\s*$', result_text, re.M):
        name, relative = match.groups()
        # MCP paths are relative to its cwd/output directory; never accept external paths.
        root = session.mcp.directory.resolve()
        raw = Path(relative)
        candidate = (root / raw).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
            continue
        cursor = root
        unsafe = False
        for part in candidate.relative_to(root).parts:
            cursor /= part
            if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
                unsafe = True
        if unsafe:
            continue
        if any(d['source'] == str(candidate) for d in session.downloads.values()):
            continue
        download_id = str(uuid.uuid4())
        saved = await service.import_unique_artifact(candidate, _available_name(name, service))
        session.downloads[download_id] = {'id': download_id, 'name': name, 'source': str(candidate), 'bytes': candidate.stat().st_size, 'path': saved['path']}
        public = {k: v for k, v in session.downloads[download_id].items() if k != 'source'}
        added.append(public)
        await session.emit({'type': 'activity', 'id': download_id, 'category': 'file', 'name': 'Download completed', 'description': name, 'status': 'success', 'details': f'Saved to Downloads: {saved["path"]}'})
    return added

