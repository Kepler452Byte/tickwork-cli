import sys
from pathlib import Path
from types import TracebackType
from typing import IO

from tickwork_cli.common.application_errors import TickworkError


class FileLock:
    """OS-owned locks survive DB deletion and release on process exit."""

    def __init__(self, path: Path, blocking: bool = True) -> None:
        self.path = path
        self.blocking = blocking
        self.handle: IO[bytes] | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except OSError as exc:
            handle.close()
            raise TickworkError(
                "busy", "Another process holds this operation lock; retry later."
            ) from exc
        self.handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.handle:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()
