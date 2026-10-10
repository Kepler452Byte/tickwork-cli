import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tickwork_cli.app.agent.service.agent_resource_service import install_resources
from tickwork_cli.app.task.repository.task_run_repository import TaskRunRepository
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.app.task.service.task_service import TaskService
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.file_lock import FileLock


class MemoryScheduler:
    def __init__(self) -> None:
        self.tasks: dict[str, tuple[Task, bool]] = {}
        self.fail_once = False

    def state(self, task_id: str) -> dict[str, Any]:
        return {
            "deployed": task_id in self.tasks,
            "enabled": self.tasks.get(task_id, (None, False))[1],
        }

    def deploy(self, task: Task, enabled: bool) -> None:
        self.tasks[task.id] = task, enabled
        if self.fail_once:
            self.fail_once = False
            raise OSError("Native deployment failed halfway")

    def remove(self, task_id: str) -> None:
        self.tasks.pop(task_id, None)

    def doctor(self) -> dict[str, Any]:
        return {"available": True}


def apply(
    service: TaskService, action: str, task: Task | None, task_id: str = "example"
) -> dict[str, Any]:
    preview = service.change(action, task_id, task, False, None)
    return service.change(action, task_id, task, True, preview["plan"])


def test_lifecycle_stale_plan_and_paused_update(tmp_path: Path, task: Task) -> None:
    scheduler = MemoryScheduler()
    service = TaskService(tmp_path, scheduler)
    preview = service.change("create", task.id, task, False, None)
    assert not (tmp_path / "tasks.yaml").exists()
    service.change("create", task.id, task, True, preview["plan"])
    assert service.show(task.id)["scheduler"]["enabled"] is False
    apply(service, "update", task)
    assert service.show(task.id)["scheduler"]["enabled"] is False
    preview = service.change("resume", task.id, None, False, None)
    scheduler.tasks[task.id] = task, True
    with pytest.raises(TickworkError, match="fresh preview"):
        service.change("resume", task.id, None, True, preview["plan"])
    apply(service, "pause", None)
    apply(service, "delete", None)
    assert service.list() == []


def test_compensation_restores_existing_definition(tmp_path: Path, task: Task) -> None:
    scheduler = MemoryScheduler()
    service = TaskService(tmp_path, scheduler)
    apply(service, "create", task)
    scheduler.fail_once = True
    with pytest.raises(TickworkError, match="restored"):
        apply(service, "resume", None)
    assert scheduler.state(task.id)["enabled"] is False
    assert service.get(task.id) == task


def test_busy_mutation_does_not_kill(tmp_path: Path, task: Task) -> None:
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", task)
    with FileLock(tmp_path / ".locks/run-example.lock", blocking=False):
        with pytest.raises(TickworkError, match="lock"):
            apply(service, "delete", None)
        assert service.get(task.id) == task


def test_runner_success_failure_timeout_and_db_rebuild(tmp_path: Path, task: Task) -> None:
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", task)
    result = service.run(task.id, True)
    assert result["status"] == "succeeded"
    assert TaskRunRepository(tmp_path).logs(result["id"], 20, 0)[0]["content"].splitlines() == [
        "hello"
    ]
    for path in tmp_path.glob("tickwork.db*"):
        path.unlink()
    assert service.get(task.id) == task
    assert TaskRunRepository(tmp_path).history(None, 20, 0) == []
    failure = Task(
        task.id,
        [sys.executable, "-c", "import sys; print('err',file=sys.stderr); sys.exit(7)"],
        task.cwd,
        task.schedule,
        5,
    )
    apply(service, "update", failure)
    result = service.run(task.id, True)
    assert result["exit_code"] == 7 and result["status"] == "failed"
    sleeper = Task(
        task.id, [sys.executable, "-c", "import time; time.sleep(10)"], task.cwd, task.schedule, 1
    )
    apply(service, "update", sleeper)
    result = service.run(task.id, True)
    assert result["status"] == "timeout" and result["duration"] < 5


def test_log_cap_and_pagination(
    tmp_path: Path, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tickwork_cli.app.task.service.task_runner.LOG_LIMIT", 100)
    noisy = Task(task.id, [sys.executable, "-c", "print('x'*20000)"], task.cwd, task.schedule, 5)
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", noisy)
    result = service.run(task.id, True)
    assert result["truncated"] == 1
    logs = TaskRunRepository(tmp_path).logs(result["id"], 100, 0)
    assert sum(len(chunk["content"]) for chunk in logs) == 100
    assert TaskRunRepository(tmp_path).logs(result["id"], 20, logs[-1]["seq"]) == []


@pytest.mark.parametrize(
    "schedule",
    [
        {"kind": "interval", "seconds": 61},
        {"kind": "daily", "time": "25:00"},
        {"kind": "weekly", "time": "09:00", "day": "bad"},
        {"kind": "interval", "seconds": True},
    ],
)
def test_invalid_schedule(task: Task, schedule: dict[str, Any]) -> None:
    with pytest.raises(TickworkError):
        Task(task.id, task.argv, task.cwd, schedule)


def test_agent_resources_preserve_content_and_reject_edited_skill(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Existing unrelated instructions\n", encoding="utf-8")
    skills = tmp_path / "skills"
    preview = install_resources(agents, skills, tmp_path, False, None)
    assert agents.read_text() == "# Existing unrelated instructions\n"
    install_resources(agents, skills, tmp_path, True, preview["plan"])
    assert agents.read_text().startswith("# Existing unrelated instructions\n")
    assert agents.read_text().count("<!-- TICKWORK:BEGIN -->") == 1
    preview = install_resources(agents, skills, tmp_path, False, None)
    install_resources(agents, skills, tmp_path, True, preview["plan"])
    skill = skills / "tickwork-task-management/SKILL.md"
    skill.write_text("Locally edited", encoding="utf-8")
    with pytest.raises(TickworkError, match="locally edited"):
        install_resources(agents, skills, tmp_path, False, None)
    assert not (tmp_path / "tasks.yaml").exists()


def test_duplicate_config_is_rejected(tmp_path: Path, task: Task) -> None:
    (tmp_path / "tasks.yaml").write_text(json.dumps({"tasks": [task.data(), task.data()]}))
    with pytest.raises(TickworkError, match="Duplicate"):
        TaskService(tmp_path, MemoryScheduler()).repository.read()


def test_can_inspect_and_delete_after_executable_disappears(tmp_path: Path, task: Task) -> None:
    executable = tmp_path / "ephemeral-executable"
    executable.write_bytes(b"unused")
    definition = Task(task.id, [str(executable)], task.cwd, task.schedule)
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", definition)
    executable.unlink()
    assert service.show(task.id)["id"] == task.id
    apply(service, "delete", None)
    assert service.list() == []


def test_comment_edit_invalidates_config_plan(tmp_path: Path, task: Task) -> None:
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", task)
    preview = service.change("pause", task.id, None, False, None)
    config = tmp_path / "tasks.yaml"
    config.write_text(config.read_text() + "\n# Concurrent user edit\n")
    with pytest.raises(TickworkError, match="fresh preview"):
        service.change("pause", task.id, None, True, preview["plan"])


def test_timeout_cleans_descendants_after_parent_exits(tmp_path: Path, task: Task) -> None:
    child = "import time; time.sleep(20)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(0.2)"
    definition = Task(task.id, [sys.executable, "-c", parent], task.cwd, task.schedule, 1)
    service = TaskService(tmp_path, MemoryScheduler())
    apply(service, "create", definition)
    result = service.run(task.id, True)
    assert result["status"] == "timeout" and result["duration"] < 5


def test_unfinished_history_is_reconciled_on_next_start(tmp_path: Path) -> None:
    repository = TaskRunRepository(tmp_path)
    repository.start("interrupted", "example", 999)
    repository.start("new", "example", 1000)
    assert repository.result("interrupted")["status"] == "interrupted"
    assert repository.result("new")["status"] == "running"
