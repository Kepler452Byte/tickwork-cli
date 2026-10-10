import hashlib
import json
from pathlib import Path
from typing import Any

from tickwork_cli.app.task.adapter.scheduler_protocol import Scheduler
from tickwork_cli.app.task.repository.task_repository import TaskRepository
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.app.task.service.task_runner import run_task
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.file_lock import FileLock


class TaskService:
    def __init__(self, home: Path, scheduler: Scheduler) -> None:
        self.home = home
        self.repository = TaskRepository(home)
        self.scheduler = scheduler

    def lock(self) -> FileLock:
        return FileLock(self.home / ".locks/config.lock")

    def run_lock(self, task_id: str) -> FileLock:
        return FileLock(self.home / f".locks/run-{task_id}.lock", blocking=False)

    def get(self, task_id: str) -> Task:
        tasks = self.repository.read()
        if task_id not in tasks:
            raise TickworkError("not-found", f"Task {task_id} does not exist")
        return tasks[task_id]

    def list(self) -> list[dict[str, Any]]:
        with self.lock():
            return [
                {**task.data(), "scheduler": self.scheduler.state(task.id)}
                for task in self.repository.read().values()
            ]

    def show(self, task_id: str) -> dict[str, Any]:
        with self.lock():
            return {**self.get(task_id).data(), "scheduler": self.scheduler.state(task_id)}

    def change(
        self, action: str, task_id: str, task: Task | None, confirm: bool, expected: str | None
    ) -> dict[str, Any]:
        with self.lock():
            tasks = self.repository.read()
            old = tasks.get(task_id)
            if action == "create" and old:
                raise TickworkError("already-exists", f"Task {task_id} exists")
            if action != "create" and old is None:
                raise TickworkError("not-found", f"Task {task_id} does not exist")
            state = self.scheduler.state(task_id)
            if action == "create" and state["deployed"]:
                raise TickworkError(
                    "already-deployed", "A native task already exists; reconcile it before creating"
                )
            enabled = action == "resume" or (action == "update" and bool(state["enabled"]))
            replacement = task or old
            payload = {
                "action": action,
                "task_id": task_id,
                "before": old.data() if old else None,
                "after": replacement.data() if action != "delete" and replacement else None,
                "scheduler_before": state,
                "enabled_after": enabled,
                "config": [item.data() for item in tasks.values()],
            }
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            plan = {
                "status": "preview",
                "plan": digest,
                **{key: value for key, value in payload.items() if key != "config"},
            }
            if not confirm:
                return plan
            if expected != digest:
                raise TickworkError(
                    "stale-plan",
                    "Use --expected-plan from a fresh preview; configuration or native state changed",
                )
            replacement = task or old
            with self.run_lock(task_id):
                try:
                    if action == "delete":
                        self.scheduler.remove(task_id)
                        del tasks[task_id]
                    else:
                        assert replacement is not None
                        self.scheduler.deploy(replacement, enabled)
                        tasks[task_id] = replacement
                    self.repository.write(tasks)
                except Exception as exc:
                    try:
                        if old:
                            self.scheduler.deploy(old, bool(state["enabled"]))
                        else:
                            self.scheduler.remove(task_id)
                    except Exception as rollback:
                        raise TickworkError(
                            "recovery-required",
                            f"Operation failed: {exc}; compensation failed: {rollback}. Inspect native scheduler and tasks.yaml.",
                        ) from exc
                    raise TickworkError(
                        "change-failed",
                        f"Operation failed and native configuration was restored: {exc}",
                    ) from exc
            return {**plan, "status": "ok", "scheduler": self.scheduler.state(task_id)}

    def run(self, task_id: str, confirm: bool, scheduled: bool = False) -> dict[str, Any]:
        # Take immutable execution input while holding config lock, then let edits proceed.
        with self.lock():
            task = self.get(task_id)
            if not confirm:
                return {"status": "preview", "action": "run", "task": task.data()}
            if scheduled and not self.scheduler.state(task_id)["enabled"]:
                raise TickworkError("paused", "Scheduled trigger ignored: task is paused")
            lock = self.run_lock(task_id)
            lock.__enter__()
        try:
            return run_task(self.home, task)
        finally:
            lock.__exit__(None, None, None)
