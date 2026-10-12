from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tickwork_cli.app.task.repository.task_run_repository import RUN_SCHEMA, TaskRunRepository
from tickwork_cli.app.task.schema.retention_schema import RetentionPolicy
from tickwork_cli.application_container import ApplicationContainer
from tickwork_cli.application_settings import ApplicationSettings
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.database.database_session import DatabaseSession
from tickwork_cli.common.time_display import display_run


@pytest.fixture
def service(tmp_path):
    container = ApplicationContainer(ApplicationSettings.load(tmp_path))
    container.initialize()
    yield container.task_service
    container.close()


def seed(service, run_id, task="example", status="succeeded", days=40, log="log"):
    now = datetime.now(UTC)
    finished = (now - timedelta(days=days)).isoformat() if status != "running" else None
    with service.runs.database.transaction() as db:
        db.execute(
            "INSERT INTO runs(id,task_id,started,finished,status) VALUES(?,?,?,?,?)",
            (run_id, task, (now - timedelta(days=100)).isoformat(), finished, status),
        )
        db.execute("INSERT INTO logs(run_id,stream,content) VALUES(?,?,?)", (run_id, "stdout", log))


def test_per_task_caps_age_minimum_and_running_exclusion():
    now = datetime.now(UTC)
    rows = [
        {
            "id": f"{task}-{status}-{i}",
            "task_id": task,
            "status": status,
            "finished": (now - timedelta(days=i + 1)).isoformat(),
        }
        for task in ["fast", "slow"]
        for status in ["succeeded", "failed", "timeout", "interrupted"]
        for i in range(5)
    ]
    rows += [{"id": "active", "task_id": "fast", "status": "running", "finished": None}]
    rows.sort(key=lambda row: row["finished"] or "", reverse=True)
    policy = RetentionPolicy(2, 2, 3, 4, 3)
    selected = set(policy.select(rows, now))
    for task in ["fast", "slow"]:
        successes = [row for row in rows if row["task_id"] == task and row["status"] == "succeeded"]
        failures = [
            row
            for row in rows
            if row["task_id"] == task and row["status"] in {"failed", "timeout", "interrupted"}
        ]
        assert len([row for row in successes if row["id"] not in selected]) == 1
        assert len([row for row in failures if row["id"] not in selected]) == 3
    assert "active" not in selected
    assert all("succeeded" in run for run in policy.select(rows, now, keep_failures=True))
    assert policy.select(rows, now, task_id="slow", statuses={"failed"}, older_than=4) == [
        "slow-failed-3",
        "slow-failed-4",
    ]


@pytest.mark.parametrize(
    "values", [{"failure_keep": 101}, {"success_limit": 0}, {"success_days": -1}]
)
def test_invalid_policy(values):
    with pytest.raises(TickworkError):
        RetentionPolicy(**values)


def test_cleanup_preview_stale_and_cascading_logs(service):
    seed(service, "old")
    seed(service, "recent", days=1)
    seed(service, "failed", status="failed")
    seed(service, "other", task="other")
    args = ("example", 7, None, True)
    preview = service.cleanup(*args, False, None)
    assert preview["delete_count"] == 1 and not preview["write_performed"]
    assert service.runs.logs("old", 20, 0)
    seed(service, "concurrent", days=2)
    with pytest.raises(TickworkError, match="preview again"):
        service.cleanup(*args, True, preview["plan"])
    preview = service.cleanup(*args, False, None)
    result = service.cleanup(*args, True, preview["plan"])
    assert result["delete_count"] == 1
    with service.runs.database.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM logs WHERE run_id='old'").fetchone()[0] == 0
    assert service.runs.result("failed")["status"] == "failed"
    assert service.runs.result("other")


def test_cleanup_only_reconciles_orphans_after_confirmation(service):
    seed(service, "orphan", task="orphan", status="running")
    seed(service, "active", task="active", status="running")
    with service.run_lock("active"):
        preview = service.cleanup(None, 0, None, False, False, None)
        assert service.runs.result("orphan")["status"] == "running"
        service.cleanup(None, 0, None, False, True, preview["plan"])
        assert service.runs.result("active")["status"] == "running"
        assert service.runs.result("orphan")["status"] == "interrupted"
        assert service.runs.result("orphan")["finished"]
    assert service.runs.result("orphan")  # Newly reconciled rows are not silently deleted.


def test_compaction_reclaims_space_and_rejects_busy_tasks(service):
    seed(service, "large", log="x" * (2 * 1024 * 1024))
    service.runs.database.close()
    old_size = service.runs.database.path.stat().st_size
    preview = service.cleanup(None, 0, None, False, False, None)
    service.cleanup(None, 0, None, False, True, preview["plan"])
    preview = service.compact(False, None)
    service.compact(True, preview["plan"])
    assert service.runs.database.path.stat().st_size < old_size // 2
    seed(service, "busy", status="running")
    with service.run_lock("example"):
        with pytest.raises(TickworkError, match="lock"):
            service.compact(False, None)


def test_empty_compaction_is_noop_and_stale_preview_rejected(service):
    preview = service.compact(False, None)
    assert not service.runs.database.path.exists()
    assert not service.compact(True, preview["plan"])["write_performed"]
    seed(service, "new")
    with pytest.raises(TickworkError, match="preview"):
        service.compact(True, preview["plan"])


def test_age_uses_finished_and_failures_remain(service):
    seed(service, "long-running", days=0)
    seed(service, "old-failure", status="failed")
    assert service.cleanup(None, None, None, False, False, None)["delete_count"] == 0


def test_automatic_cleanup_cascades_at_start(service, tmp_path):
    import sys

    from tickwork_cli.app.task.schema.task_schema import Task

    task = Task(
        "example", [sys.executable, "-c", "print('new')"], str(tmp_path), {"kind": "manual"}
    )
    service.repository.write({task.id: task})
    seed(service, "old-success")
    seed(service, "old-failure", status="failed")
    assert service.run(task.id, True)["status"] == "succeeded"
    with pytest.raises(TickworkError, match="does not exist"):
        service.runs.result("old-success")
    assert service.runs.result("old-failure")


def test_utc_storage_and_display_cross_day_dst(service):
    run = {"started": "2026-03-08T06:59:00+00:00", "finished": "2026-03-08T07:01:00+00:00"}
    ny = display_run(run, "America/New_York")
    assert ny["started"] == run["started"]
    assert ny["display_time"]["started"] == "2026-03-08T01:59:00-05:00"
    assert ny["display_time"]["finished"] == "2026-03-08T03:01:00-04:00"
    china = display_run({"started": "2026-10-12T23:00:00+00:00", "finished": None}, "Asia/Shanghai")
    assert china["display_time"]["started"] == "2026-10-13T07:00:00+08:00"
    assert china["display_time"]["finished"] is None
    assert display_run(run, "UTC")["display_time"]["started"] == run["started"]
    assert display_run(run, "local")["display_time"]["started"]
    with pytest.raises(TickworkError, match="timezone"):
        service.history(None, 20, 0, "invalid/zone")
    assert not service.runs.database.path.exists()


def test_repository_delete_guard_never_deletes_running(tmp_path: Path):
    database = DatabaseSession(tmp_path / "tickwork.db")
    database.initialize(RUN_SCHEMA)
    runs = TaskRunRepository(database)
    try:
        runs.start("active", "task", 123)
        assert runs.delete_completed(["active"]) == 0
        assert runs.result("active")["status"] == "running"
    finally:
        database.close()


def test_automatic_count_cap_includes_new_completion(service, tmp_path):
    import sys

    from tickwork_cli.app.task.schema.task_schema import Task

    service.policy = RetentionPolicy(7, 30, 2, 2, 1)
    task = Task("example", [sys.executable, "-c", "pass"], str(tmp_path), {"kind": "manual"})
    service.repository.write({task.id: task})
    seed(service, "first", days=1)
    seed(service, "second", days=1)
    seed(service, "failure-1", status="failed", days=1)
    seed(service, "failure-2", status="failed", days=1)
    seed(service, "failure-3", status="failed", days=1)
    result = service.run(task.id, True)
    rows = service.runs.completed()
    assert sum(row["status"] == "succeeded" for row in rows) == 2
    assert sum(row["status"] == "failed" for row in rows) == 2
    assert service.runs.result(result["id"])
