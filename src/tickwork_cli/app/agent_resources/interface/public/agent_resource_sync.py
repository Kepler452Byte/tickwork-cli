"""Public resource alignment port used by system upgrade."""

from pathlib import Path
from typing import Protocol


class IAgentResourceSync(Protocol):
    def sync(
        self,
        confirm: bool = False,
        expected_plan: str | None = None,
        skills_dir: Path | None = None,
        hint_file: Path | None = None,
    ) -> dict[str, object]: ...
