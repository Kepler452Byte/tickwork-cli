import hashlib
import json
from pathlib import Path
from typing import Any

from tickwork_cli.app.task.adapter.scheduler_protocol import Scheduler
from tickwork_cli.app.task.repository.task_repository import TaskRepository
from tickwork_cli.app.task.repository.task_run_repository import TaskRunRepository
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.app.task.service.task_runner import run_task
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.file_lock import FileLock


class TaskService:
    def __init__(
        self, home: Path, scheduler: Scheduler, repository: TaskRepository, runs: TaskRunRepository
    ) -> None:
        self.home = home
        self.repository = repository
        self.runs = runs
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

    def state(self, task: Task) -> dict[str, Any]:
        if task.schedule["kind"] == "manual":
            return {"deployed": False, "enabled": False, "active": False, "details": {}}
        return self.scheduler.state(task.id)

    def follow_up(self, task_id: str) -> list[dict[str, Any]]:
        return [
            {
                "argv": ["tickwork", "--home", str(self.home), "task", "run", task_id],
                "reason": "Test the configured command; execution requires user authorization",
                "requires_execution_authorization": True,
            }
        ]

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.lock():
            return [
                {**task.data(), "scheduler": self.state(task)}
                for task in self.repository.read().values()
            ]

    def show(self, task_id: str) -> dict[str, Any]:
        with self.lock():
            return {**self.get(task_id).data(), "scheduler": self.state(self.get(task_id))}

    def change(
        self, action: str, task_id: str, task: Task | None, confirm: bool, expected: str | None
    ) -> dict[str, Any]:
        if task is not None and (not Path(task.argv[0]).is_file() or not Path(task.cwd).is_dir()):
            raise TickworkError(
                "invalid-task",
                "Executable and working directory must exist when creating or updating",
            )
        with self.lock():
            tasks = self.repository.read()
            old = tasks.get(task_id)
            if action == "create" and old:
                raise TickworkError("already-exists", f"Task {task_id} exists")
            if action != "create" and old is None:
                raise TickworkError("not-found", f"Task {task_id} does not exist")
            replacement = task or old
            assert replacement is not None
            manual = replacement.schedule["kind"] == "manual"
            if action in {"pause", "resume"} and manual:
                raise TickworkError(
                    "schedule-not-applicable", "Manual tasks have no schedule to pause or resume"
                )
            native_change = not manual or (old is not None and old.schedule["kind"] != "manual")
            state = self.scheduler.state(task_id) if native_change else self.state(replacement)
            if action == "create" and state["deployed"]:
                raise TickworkError(
                    "already-deployed", "A native task already exists; reconcile it before creating"
                )
            enabled = not manual and (
                action == "resume"
                or (
                    action == "update"
                    and old is not None
                    and old.schedule["kind"] != "manual"
                    and bool(state["enabled"])
                )
            )
            payload = {
                "action": action,
                "task_id": task_id,
                "before": old.data() if old else None,
                "after": replacement.data() if action != "delete" and replacement else None,
                "scheduler_before": state,
                "enabled_after": enabled,
                "config": hashlib.sha256(self.repository.path.read_bytes()).hexdigest()
                if self.repository.path.exists()
                else "missing",
            }
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            plan: dict[str, Any] = {
                "status": "preview",
                "follow_up": [],
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
            with self.run_lock(task_id):
                try:
                    if action == "delete":
                        if native_change:
                            self.scheduler.remove(task_id)
                        del tasks[task_id]
                    else:
                        assert replacement is not None
                        if manual:
                            if native_change:
                                self.scheduler.remove(task_id)
                        else:
                            self.scheduler.deploy(replacement, enabled)
                        tasks[task_id] = replacement
                    self.repository.write(tasks)
                except Exception as exc:
                    try:
                        if old and state["deployed"]:
                            self.scheduler.deploy(old, bool(state["enabled"]))
                        elif native_change:
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
            changed_execution = old is None or (
                replacement.argv,
                replacement.cwd,
                replacement.timeout,
            ) != (old.argv, old.cwd, old.timeout)
            return {
                **plan,
                "status": "ok",
                "scheduler": self.state(replacement),
                "follow_up": self.follow_up(task_id)
                if action in {"create", "update"} and changed_execution
                else [],
            }

    def run(self, task_id: str, confirm: bool, scheduled: bool = False) -> dict[str, Any]:
        # Take immutable execution input while holding config lock, then let edits proceed.
        with self.lock():
            task = self.get(task_id)
            if not confirm:
                return {"status": "preview", "action": "run", "task": task.data()}
            if scheduled and not self.state(task)["enabled"]:
                raise TickworkError("paused", "Scheduled trigger ignored: task is paused")
            lock = self.run_lock(task_id)
            lock.__enter__()
        try:
            return run_task(task, self.runs)
        finally:
            lock.__exit__(None, None, None)

    def history(self, task_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        self.validate_page(limit, offset)
        return self.runs.history(task_id, limit, offset)

    def result(self, run_id: str) -> dict[str, Any]:
        return self.runs.result(run_id)

    def logs(self, run_id: str, limit: int, after: int) -> dict[str, Any]:
        self.validate_page(limit, after)
        chunks = self.runs.logs(run_id, limit, after)
        return {
            "chunks": chunks,
            "next_cursor": chunks[-1]["seq"] if chunks else after,
            "truncated": self.runs.result(run_id)["truncated"] == 1,
        }

    @staticmethod
    def validate_page(limit: int, cursor: int) -> None:
        if not 1 <= limit <= 100 or cursor < 0:
            raise TickworkError(
                "invalid-page", "limit must be 1..100 and offset/cursor nonnegative"
            )

    def run_follow_up(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "argv": ["tickwork", "--home", str(self.home), "task", action, run_id],
                "reason": "Inspect this run and verify expected artifacts",
                "requires_execution_authorization": False,
            }
            for action in ("result", "logs")
        ]
