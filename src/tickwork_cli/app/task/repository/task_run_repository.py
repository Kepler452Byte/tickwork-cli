from datetime import UTC, datetime, timedelta
from typing import Any

from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.database.database_session import DatabaseSession

RUN_SCHEMA = """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, started TEXT NOT NULL,
            finished TEXT, status TEXT NOT NULL, exit_code INTEGER,
            duration REAL, truncated INTEGER NOT NULL DEFAULT 0, pid INTEGER
        );
        CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id, started);
        CREATE TABLE IF NOT EXISTS logs (
            seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            stream TEXT NOT NULL, content TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS logs_run ON logs(run_id, seq);
    """

LOG_LIMIT = 10 * 1024 * 1024
RETENTION_DAYS = 30
MAX_RUNS = 100


class TaskRunRepository:
    def __init__(self, database: DatabaseSession) -> None:
        self.database = database

    def start(self, run_id: str, task_id: str, pid: int) -> None:
        with self.database.transaction() as db:
            # The caller holds this task's OS run lock: prior unfinished rows cannot be active.
            db.execute(
                "UPDATE runs SET status='interrupted', finished=? WHERE task_id=? AND status='running'",
                (datetime.now(UTC).isoformat(), task_id),
            )
            cutoff = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS)).isoformat()
            db.execute("DELETE FROM runs WHERE started < ?", (cutoff,))
            db.execute(
                "DELETE FROM runs WHERE id IN (SELECT id FROM runs WHERE finished IS NOT NULL ORDER BY started DESC LIMIT -1 OFFSET ?)",
                (MAX_RUNS - 1,),
            )
            db.execute(
                "INSERT INTO runs(id,task_id,started,status,pid) VALUES (?,?,?,?,?)",
                (run_id, task_id, datetime.now(UTC).isoformat(), "running", pid),
            )

    def append(self, run_id: str, stream: str, content: str) -> None:
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO logs(run_id,stream,content) VALUES (?,?,?)", (run_id, stream, content)
            )

    def finish(
        self, run_id: str, status: str, code: int | None, duration: float, truncated: bool
    ) -> None:
        with self.database.transaction() as db:
            db.execute(
                "UPDATE runs SET finished=?,status=?,exit_code=?,duration=?,truncated=? WHERE id=?",
                (datetime.now(UTC).isoformat(), status, code, duration, int(truncated), run_id),
            )

    def history(self, task_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        with self.database.transaction() as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE (? IS NULL OR task_id=?) ORDER BY started DESC LIMIT ? OFFSET ?",
                (task_id, task_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def result(self, run_id: str) -> dict[str, Any]:
        with self.database.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise TickworkError("not-found", "Run does not exist")
        return dict(row)

    def logs(self, run_id: str, limit: int, after: int) -> list[dict[str, Any]]:
        self.result(run_id)
        with self.database.transaction() as db:
            rows = db.execute(
                "SELECT seq,stream,content FROM logs WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after, limit),
            ).fetchall()
        return [dict(row) for row in rows]
