import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from tickwork_cli.app.task.schema.task_schema import Task


class Scheduler(Protocol):
    def state(self, task_id: str) -> dict[str, Any]: ...
    def deploy(self, task: Task, enabled: bool) -> None: ...
    def remove(self, task_id: str) -> None: ...
    def doctor(self) -> dict[str, Any]: ...


def namespace(home: Path) -> str:
    return "tickwork-" + hashlib.sha256(str(home).encode()).hexdigest()[:12]


def runner_argv(home: Path, task_id: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tickwork_cli.main",
        "--home",
        str(home),
        "task",
        "run",
        task_id,
        "--confirm",
        "--scheduled",
    ]


def marker(home: Path, task_id: str) -> str:
    return json.dumps({"owner": "tickwork", "home": str(home), "id": task_id}, sort_keys=True)
