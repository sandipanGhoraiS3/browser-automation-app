import os
from pathlib import Path, PureWindowsPath

class WorkspacePolicy:
    """An explicit root capability; future approved roots use separate policy instances."""
    def __init__(self, root: Path, blocked_names=None):
        self.root = root.resolve()
        self.blocked_names = {name.casefold() for name in (blocked_names or ())}
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, value: str, allow_root=False) -> Path:
        if not value or '\x00' in value:
            raise ValueError('A workspace-relative path is required.')
        # Reject drive-relative paths, UNC, ADS, traversal and Windows device aliases on every OS.
        normalized = value.replace('\\', '/')
        parts = normalized.split('/')
        first = next((part for part in parts if part not in ('', '.')), '')
        if first.casefold() in self.blocked_names:
            raise ValueError('The requested path is reserved for another workspace.')
        windows = PureWindowsPath(value)
        reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
        if windows.drive or normalized.startswith('/') or '..' in parts or ':' in normalized:
            raise ValueError('The requested path is outside the allowed workspace. Use a relative path.')
        for part in parts:
            if part in ('', '.'):
                continue
            if part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved or any(c in part for c in '<>"|?*'):
                raise ValueError('This filename is not allowed.')
        candidate = self.root.joinpath(*parts)
        # No symlinks/junctions, including links whose destination is still under the root.
        cursor = self.root
        for part in candidate.relative_to(self.root).parts:
            cursor /= part
            if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
                raise ValueError('Symbolic links and junctions are not allowed in the workspace.')
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root) or (resolved == self.root and not allow_root):
            raise ValueError('The requested path is outside the allowed workspace or targets its root.')
        if resolved.exists() and resolved.is_file() and os.stat(resolved).st_nlink > 1:
            raise ValueError('Hard-linked files are not allowed.')
        return resolved

    def relative(self, path: Path):
        return path.relative_to(self.root).as_posix()


