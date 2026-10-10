import os
import tempfile
from pathlib import Path

import yaml

from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.common.application_errors import TickworkError


class TaskRepository:
    def __init__(self, home: Path) -> None:
        self.path = home / "tasks.yaml"

    def read(self) -> dict[str, Task]:
        if not self.path.exists():
            return {}
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TickworkError("invalid-config", str(exc)) from exc
        if (
            not isinstance(data, dict)
            or set(data) != {"tasks"}
            or not isinstance(data["tasks"], list)
        ):
            raise TickworkError("invalid-config", "tasks.yaml requires one tasks array")
        tasks = [Task.parse(item) for item in data["tasks"]]
        if len({task.id for task in tasks}) != len(tasks):
            raise TickworkError("invalid-config", "Duplicate task ids")
        return {task.id: task for task in tasks}

    def write(self, tasks: dict[str, Task]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".tasks-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {"tasks": [task.data() for task in tasks.values()]},
                    handle,
                    allow_unicode=True,
                    sort_keys=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
