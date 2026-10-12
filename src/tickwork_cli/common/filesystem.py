"""Safe file operations with per-file atomic replacement and cooperative locking."""

import os
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from tickwork_cli.common.file_lock import FileLock
from tickwork_cli.common.operation_error import OperationError


def safe_path(path: Path) -> Path:
    """Reject symlink ancestors before resolving explicit installation targets."""
    path = path.expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise OperationError("Symbolic links are not valid managed targets", "unsafe-path")
    return path.resolve()


def read_bytes(path: Path) -> bytes | None:
    safe_path(path)
    if path.exists() and not path.is_file():
        raise OperationError("Managed target is not a regular file", "unsafe-path")
    return path.read_bytes() if path.is_file() else None


def atomic_write(path: Path, content: bytes) -> None:
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".agent-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(name, path.stat().st_mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def write_lock(root: Path, targets: list[Path] | None = None) -> Iterator[None]:
    """Serialize cooperating writers, including products sharing one Hint file."""
    safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    locks = [root / "write.lock"]
    locks.extend(
        sorted(
            {
                safe_path(path).with_name("." + path.name + ".agent-write.lock")
                for path in targets or []
            }
        )
    )
    with ExitStack() as stack:
        for lock in locks:
            safe_path(lock)
            stack.enter_context(FileLock(lock, blocking=False))
        yield
