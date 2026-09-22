import asyncio
import os
import shutil
import threading
from pathlib import Path
from app.config import ROOT, settings
from app.file_agent.formats import encode_file
from app.file_agent.security import WorkspacePolicy


def user_downloads_directory() -> Path:
    """Return the OS Downloads known folder, including redirected Windows profiles."""
    if os.name == 'nt':
        try:
            import winreg
            key_path = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')
                return Path(os.path.expandvars(value)).expanduser()
        except OSError:
            pass
    return Path.home() / 'Downloads'

class FileService:
    def __init__(self, root=None, max_bytes=None, blocked_names=None):
        self.policy = WorkspacePolicy(Path(root) if root else ROOT / settings.file_workspace_root, blocked_names)
        self.max_bytes = max_bytes or settings.file_max_bytes
        self.lock = threading.RLock()

    async def execute(self, operation, args):
        task = asyncio.create_task(asyncio.to_thread(self._execute, operation, args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A filesystem mutation is not interruptible mid-write. Finish it before releasing the run.
            await task
            raise

    def _execute(self, operation, args):
        with self.lock:
            try:
                return self._operate(operation, args)
            except (ValueError, FileExistsError):
                raise
            except FileNotFoundError as exc:
                raise ValueError('The requested file or parent folder does not exist.') from exc
            except PermissionError as exc:
                raise ValueError('The operating system denied access to this file.') from exc
            except OSError as exc:
                raise ValueError('Unable to complete this file operation. Check the path and available disk space.') from exc

    def _operate(self, operation, args):
        path = self.policy.resolve(args.get('path', '.'), allow_root=operation in ('list_directory', 'file_exists', 'folder_exists')) if operation not in ('copy_file', 'move_file', 'rename_file') else None
        if operation == 'create_folder':
            path.mkdir(parents=True, exist_ok=True)
        elif operation in ('create_file', 'write_file', 'append_file'):
            office = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
            if operation == 'append_file' and (path.suffix.lower() in office or args.get('encoding') == 'base64'):
                raise ValueError('Appending is supported only for UTF-8 text formats.')
            encoded = encode_file(path, args['content'], args.get('encoding', 'utf-8'))
            existing = path.stat().st_size if path.exists() else 0
            if len(encoded) + (existing if operation == 'append_file' else 0) > self.max_bytes:
                raise ValueError('File exceeds the configured size limit.')
            if path.exists() and operation != 'append_file' and (operation == 'create_file' or not args.get('overwrite')):
                raise FileExistsError('File already exists. Choose another name or explicitly request overwrite.')
            if operation == 'append_file':
                with path.open('ab') as target:
                    target.write(encoded)
            elif args.get('overwrite') and operation == 'write_file':
                temporary = path.with_name('.' + path.name + '.orbit-tmp')
                # Exclusive temporary creation prevents collisions and link substitution.
                with temporary.open('xb') as target:
                    target.write(encoded)
                os.replace(temporary, path)
            else:
                with path.open('xb') as target:
                    target.write(encoded)
        elif operation == 'read_file':
            if path.stat().st_size > min(self.max_bytes, 1_000_000):
                raise ValueError('File is too large to read into the agent context.')
            try:
                return {'path': self.policy.relative(path), 'content': path.read_text(encoding='utf-8')}
            except UnicodeDecodeError as exc:
                raise ValueError('Only UTF-8 text files can be read into chat.') from exc
        elif operation == 'list_directory':
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
                if len(entries) >= 500:
                    break
                try:
                    checked = self.policy.resolve(self.policy.relative(child))
                    entries.append({'name': child.name, 'kind': 'folder' if checked.is_dir() else 'file', 'bytes': checked.stat().st_size if checked.is_file() else None})
                except ValueError:
                    continue
            return {'path': self.policy.relative(path), 'entries': entries, 'limit': 500}
        elif operation in ('file_exists', 'folder_exists'):
            return {'path': self.policy.relative(path), 'exists': path.is_file() if operation == 'file_exists' else path.is_dir()}
        elif operation in ('copy_file', 'move_file', 'rename_file'):
            source = self.policy.resolve(args['source'])
            path = self.policy.resolve(args['destination'])
            self._copy(source, path)
            if operation != 'copy_file':
                source.unlink()
        elif operation == 'delete_file':
            if not path.is_file():
                raise ValueError('Only regular files can be deleted; recursive folder deletion is not supported.')
            path.unlink()
        else:
            raise ValueError('Unknown file operation.')
        return {'ok': True, 'operation': operation, 'path': self.policy.relative(path)}

    def _copy(self, source, destination):
        if not source.is_file() or source.is_symlink():
            raise ValueError('The source is not a regular file.')
        if source.stat().st_size > self.max_bytes:
            raise ValueError('File exceeds the configured size limit.')
        if destination.exists():
            raise FileExistsError('Destination already exists. Choose another filename.')
        try:
            with source.open('rb') as src, destination.open('xb') as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        except FileExistsError:
            raise FileExistsError('Destination already exists. Choose another filename.') from None

    async def import_artifact(self, source: Path, destination: str):
        def copy():
            with self.lock:
                target = self.policy.resolve(destination)
                self._copy(source, target)
                return {'ok': True, 'path': self.policy.relative(target), 'bytes': target.stat().st_size}
        task = asyncio.create_task(asyncio.to_thread(copy))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def import_unique_artifact(self, source: Path, filename: str):
        def copy():
            with self.lock:
                requested = self.policy.resolve(filename)
                stem, suffix = requested.stem, requested.suffix
                target, number = requested, 2
                while target.exists():
                    target = self.policy.resolve(f'{stem} ({number}){suffix}')
                    number += 1
                self._copy(source, target)
                return {'ok': True, 'path': self.policy.relative(target), 'bytes': target.stat().st_size}
        task = asyncio.create_task(asyncio.to_thread(copy))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

files = FileService()
downloads = FileService(user_downloads_directory(), blocked_names={'Orbit Workspaces'})


