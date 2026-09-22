import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.browser import downloads as browser_downloads
from app.file_agent.service import FileService
from app.file_agent.security import WorkspacePolicy
from app.skills.registry import SkillRegistry
from app.skills.models import CreateSkill, SkillMetadata

INSTRUCTIONS = '''## Preconditions
Workspace available.
## Steps
1. Inspect the current page and save observed data.
## Output
Saved report path.
## Browser Rules
Fresh snapshots. Keep browser open.
## Recovery
Inspect errors and ask for missing information.
'''

@pytest.mark.asyncio
async def test_file_lifecycle(tmp_path):
    service = FileService(tmp_path / 'workspace')
    await service.execute('create_folder', {'path': 'reports'})
    await service.execute('create_file', {'path': 'reports/report.txt', 'content': 'one'})
    await service.execute('append_file', {'path': 'reports/report.txt', 'content': '\ntwo'})
    assert (await service.execute('read_file', {'path': 'reports/report.txt'}))['content'] == 'one\ntwo'
    await service.execute('write_file', {'path': 'reports/report.txt', 'content': 'updated', 'overwrite': True})
    assert (await service.execute('read_file', {'path': 'reports/report.txt'}))['content'] == 'updated'
    await service.execute('copy_file', {'source': 'reports/report.txt', 'destination': 'reports/copy.txt'})
    await service.execute('rename_file', {'source': 'reports/copy.txt', 'destination': 'reports/renamed.txt'})
    await service.execute('move_file', {'source': 'reports/renamed.txt', 'destination': 'moved.txt'})
    assert (await service.execute('file_exists', {'path': 'moved.txt'}))['exists']
    assert (await service.execute('folder_exists', {'path': 'reports'}))['exists']
    assert len((await service.execute('list_directory', {'path': '.'}))['entries']) == 2
    await service.execute('delete_file', {'path': 'moved.txt'})
    assert not (await service.execute('file_exists', {'path': 'moved.txt'}))['exists']

@pytest.mark.parametrize('path', ['../escape', '../../Windows/System32', '/etc/passwd', r'C:\Windows\file', r'C:relative', r'\\server\share', 'file:secret', 'NUL.txt', 'folder./file', r'a\..\b', '.', 'CON'])
def test_path_rejection(tmp_path, path):
    with pytest.raises(ValueError):
        WorkspacePolicy(tmp_path).resolve(path)

def test_symlink_and_hardlink_rejection(tmp_path):
    workspace = tmp_path / 'root'
    policy = WorkspacePolicy(workspace)
    external = tmp_path / 'outside.txt'
    external.write_text('private')
    os.link(external, workspace / 'hard.txt')
    with pytest.raises(ValueError):
        policy.resolve('hard.txt')
    try:
        (workspace / 'linked').symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        return  # Windows may deny symlink creation; hard-link protection was still exercised.
    with pytest.raises(ValueError):
        policy.resolve('linked/outside.txt')

@pytest.mark.asyncio
async def test_no_overwrite_and_size_cap(tmp_path):
    service = FileService(tmp_path, max_bytes=10)
    await service.execute('create_file', {'path': 'a', 'content': 'hello'})
    with pytest.raises(FileExistsError):
        await service.execute('create_file', {'path': 'a', 'content': 'bad'})
    with pytest.raises(ValueError):
        await service.execute('append_file', {'path': 'a', 'content': 'much too long'})
    assert (tmp_path / 'a').read_text() == 'hello'
    with pytest.raises(ValueError):
        await service.execute('delete_file', {'path': '.'})


@pytest.mark.asyncio
async def test_common_document_formats_and_binary_content(tmp_path):
    service = FileService(tmp_path / 'downloads')
    for suffix in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'md'):
        await service.execute('create_file', {'path': f'report.{suffix}', 'content': 'Title\nName,Value\nAlpha,1'})
    assert (tmp_path / 'downloads/report.pdf').read_bytes().startswith(b'%PDF-')
    assert (tmp_path / 'downloads/report.doc').read_bytes().startswith(b'{\\rtf')
    assert (tmp_path / 'downloads/report.xls').read_bytes().startswith(b'<?xml')
    assert b'PowerPoint.Slide' in (tmp_path / 'downloads/report.ppt').read_bytes()
    for name, member in [('report.docx', 'word/document.xml'), ('report.xlsx', 'xl/worksheets/sheet1.xml'), ('report.pptx', 'ppt/slides/slide1.xml')]:
        with zipfile.ZipFile(tmp_path / 'downloads' / name) as archive:
            assert member in archive.namelist()
    await service.execute('create_file', {'path': 'image.bin', 'content': 'AAEC', 'encoding': 'base64'})
    assert (tmp_path / 'downloads/image.bin').read_bytes() == b'\x00\x01\x02'


@pytest.mark.asyncio
async def test_browser_download_is_copied_to_pc_downloads_immediately(tmp_path, monkeypatch):
    session_root = tmp_path / 'session'
    session_root.mkdir()
    (session_root / 'report.csv').write_text('name,value\nAlpha,1')
    target = FileService(tmp_path / 'downloads')
    monkeypatch.setattr(browser_downloads, 'downloads', target)
    events = []

    async def emit(event):
        events.append(event)

    session = SimpleNamespace(mcp=SimpleNamespace(directory=session_root), downloads={}, emit=emit)
    detected = await browser_downloads.detect_downloads(session, '- Downloaded file report.csv to "report.csv"')
    assert (tmp_path / 'downloads/report.csv').read_text() == 'name,value\nAlpha,1'
    assert detected[0]['path'] == 'report.csv'
    assert 'Saved to Downloads' in events[0]['details']

def request(name='test_job', instructions=INSTRUCTIONS):
    return CreateSkill(metadata=SkillMetadata(name=name, display_name='Test Job', description='A reusable test job'), instructions=instructions)

def test_skill_create_discover_edit_delete(tmp_path):
    registry = SkillRegistry(tmp_path)
    created = registry.create(request())
    assert (tmp_path / 'test_job/skill.md').exists()
    assert registry.discover()['skills'][0]['metadata']['name'] == 'test_job'
    assert registry.resolve_command('/run test_job').metadata.name == 'test_job'
    assert registry.resolve_command('Run skill: test_job').metadata.name == 'test_job'
    with pytest.raises(ValueError, match='already exists'):
        registry.create(request())
    changed = registry.edit('test_job', created.markdown.replace('Saved report path.', 'Saved CSV path.'), created.revision)
    assert changed.revision != created.revision
    with pytest.raises(ValueError, match='changed'):
        registry.edit('test_job', created.markdown, created.revision)
    registry.delete('test_job')
    assert not registry.discover()['skills']

@pytest.mark.parametrize('bad', ['no frontmatter', '---\nname: bad\n---\n## Steps\nDo stuff'])
def test_invalid_skill(tmp_path, bad):
    registry = SkillRegistry(tmp_path)
    folder = tmp_path / 'bad'
    folder.mkdir()
    (folder / 'skill.md').write_text(bad)
    result = registry.discover()
    assert not result['skills'] and result['errors']

@pytest.mark.parametrize('bad', ['click element ref e42', 'click(100, 200)', 'password=secretvalue'])
def test_skill_rejects_brittle_or_secret_content(tmp_path, bad):
    with pytest.raises(ValueError):
        SkillRegistry(tmp_path).create(request(instructions=INSTRUCTIONS + '\n' + bad))
