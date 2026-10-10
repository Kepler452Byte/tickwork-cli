import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApplicationSettings:
    home: Path

    @classmethod
    def load(cls, home: Path | None = None) -> "ApplicationSettings":
        selected = (
            home
            if home is not None
            else Path(os.getenv("TICKWORK_HOME", str(Path.home() / ".tickwork")))
        )
        return cls(selected.expanduser().resolve())

    @property
    def database_path(self) -> Path:
        return self.home / "tickwork.db"
