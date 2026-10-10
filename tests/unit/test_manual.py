import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.application_container import ApplicationContainer
from tickwork_cli.application_settings import ApplicationSettings
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.file_lock import FileLock

from .test_tasks import MemoryScheduler, apply


class UnavailableScheduler(MemoryScheduler):
    def state(self, task_id: str) -> dict[str, Any]:
        raise AssertionError("Manual operations must not query native scheduling")

    def deploy(self, task: Task, enabled: bool) -> None:
        raise AssertionError("Manual tasks must not be deployed")

    def remove(self, task_id: str) -> None:
        raise AssertionError("Manual deletion must not modify native scheduling")


def test_manual_without_scheduler_and_follow_up(tmp_path: Path, task: Task) -> None:
    container = ApplicationContainer(ApplicationSettings.load(tmp_path))
    container.scheduler = UnavailableScheduler()
    container.initialize()
    try:
        service = container.task_service
        manual = replace(task, schedule={"kind": "manual"})
        assert service.change("create", manual.id, manual, False, None)["follow_up"] == []
        created = apply(service, "create", manual)
        assert not created["scheduler"]["deployed"]
        assert created["follow_up"][0]["argv"][-3:] == ["task", "run", manual.id]
        assert created["follow_up"][0]["requires_execution_authorization"]
        assert service.list_tasks()[0]["schedule"] == {"kind": "manual"}
        for action in ("pause", "resume"):
            with pytest.raises(TickworkError, match="no schedule"):
                apply(service, action, None)
        assert apply(service, "update", manual)["follow_up"] == []
        changed = replace(manual, argv=[sys.executable, "-c", "print('updated')"])
        assert apply(service, "update", changed)["follow_up"]
        with FileLock(tmp_path / ".locks/run-example.lock", blocking=False):
            with pytest.raises(TickworkError, match="lock"):
                apply(service, "delete", None)
        with pytest.raises(TickworkError, match="paused"):
            service.run(manual.id, True, scheduled=True)
        result = service.run(manual.id, True)
        assert result["status"] == "succeeded"
        assert "updated" in service.logs(result["id"], 20, 0)["chunks"][0]["content"]
        assert all(step["argv"][-1] == result["id"] for step in service.run_follow_up(result["id"]))
        assert not any(
            step["requires_execution_authorization"] for step in service.run_follow_up(result["id"])
        )
        apply(service, "delete", None)
        assert service.list_tasks() == []
    finally:
        container.close()


def test_mode_switches_and_failure_compensation(
    tmp_path: Path, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = ApplicationContainer(ApplicationSettings.load(tmp_path))
    scheduler = MemoryScheduler()
    container.scheduler = scheduler
    container.initialize()
    try:
        service = container.task_service
        apply(service, "create", task)
        apply(service, "resume", None)
        manual = replace(task, schedule={"kind": "manual"})
        original = service.repository.write
        monkeypatch.setattr(
            service.repository, "write", lambda tasks: (_ for _ in ()).throw(OSError("disk failed"))
        )
        with pytest.raises(TickworkError, match="restored"):
            apply(service, "update", manual)
        assert scheduler.state(task.id)["enabled"]
        assert service.get(task.id) == task
        monkeypatch.setattr(service.repository, "write", original)
        converted = apply(service, "update", manual)
        assert not scheduler.state(task.id)["deployed"]
        assert converted["follow_up"] == []
        scheduler.fail_once = True
        with pytest.raises(TickworkError, match="restored"):
            apply(service, "update", task)
        assert service.get(task.id) == manual
        assert not scheduler.state(task.id)["deployed"]
        converted = apply(service, "update", task)
        assert converted["scheduler"]["deployed"] and not converted["scheduler"]["enabled"]
        assert converted["follow_up"] == []
    finally:
        container.close()


@pytest.mark.parametrize(
    "schedule", [{"kind": "manual", "seconds": 60}, {"kind": "manual", "time": "09:00"}]
)
def test_manual_rejects_timing_fields(task: Task, schedule: dict[str, Any]) -> None:
    with pytest.raises(TickworkError):
        replace(task, schedule=schedule)
