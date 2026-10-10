import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.file_lock import FileLock

BEGIN = "<!-- TICKWORK:BEGIN -->"
END = "<!-- TICKWORK:END -->"


def install_resources(
    agents_file: Path, skills_dir: Path, home: Path, confirm: bool, expected: str | None
) -> dict[str, Any]:
    root = files("tickwork_cli") / "resources"
    destinations = {
        skills_dir / "tickwork-task-management/SKILL.md": (
            root / "skills/tickwork-task-management/SKILL.md"
        ).read_text(encoding="utf-8"),
        skills_dir / "tickwork-task-management/references/platform-notes.md": (
            root / "skills/tickwork-task-management/references/platform-notes.md"
        ).read_text(encoding="utf-8"),
    }
    owned = skills_dir / "tickwork-task-management/.tickwork-owned.json"
    with FileLock(home / ".locks/resources.lock"):
        original = agents_file.read_text(encoding="utf-8") if agents_file.exists() else ""
        hint = (
            BEGIN
            + "\n"
            + (root / "agent_hint.md").read_text(encoding="utf-8").rstrip()
            + "\n"
            + END
        )
        if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
            raise TickworkError("invalid-hint", "AGENTS file has malformed Tickwork markers")
        if BEGIN in original:
            before, remainder = original.split(BEGIN)
            _, after = remainder.split(END)
            updated = before + hint + after
        else:
            updated = original + ("\n\n" if original else "") + hint + "\n"
        previous = json.loads(owned.read_text(encoding="utf-8")) if owned.exists() else {}
        snapshots: dict[str, str | None] = {}
        for path, content in destinations.items():
            existing = path.read_text(encoding="utf-8") if path.exists() else None
            snapshots[str(path)] = existing
            digest = hashlib.sha256(existing.encode()).hexdigest() if existing is not None else None
            if existing is not None and existing != content and previous.get(str(path)) != digest:
                raise TickworkError(
                    "foreign-resource", f"Refusing to overwrite unowned or locally edited {path}"
                )
        snapshot = {
            "agents_file": str(agents_file),
            "before": original,
            "after": updated,
            "files": snapshots,
            "contents": {str(path): value for path, value in destinations.items()},
            "ownership": previous,
        }
        plan = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        result: dict[str, Any] = {
            "status": "preview",
            "plan": plan,
            "agents_file": str(agents_file),
            "skill_files": [str(path) for path in destinations],
            "tasks_changed": False,
        }
        if not confirm:
            return result
        if expected != plan:
            raise TickworkError(
                "stale-plan", "Resource files changed; preview again and pass --expected-plan"
            )
        # Limited owned-file writes; no task mutation or native scheduling calls.
        try:
            agents_file.parent.mkdir(parents=True, exist_ok=True)
            agents_file.write_text(updated, encoding="utf-8")
            for path, content in destinations.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            owned.write_text(
                json.dumps(
                    {
                        str(path): hashlib.sha256(content.encode()).hexdigest()
                        for path, content in destinations.items()
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise TickworkError(
                "resource-install-failed",
                f"{exc}; some resource files may have been written. Preview and retry.",
            ) from exc
        return {**result, "status": "ok"}
