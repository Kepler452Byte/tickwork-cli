from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.database.database_session import connect

LOG_LIMIT = 10 * 1024 * 1024
RETENTION_DAYS = 30
MAX_RUNS = 100


class TaskRunRepository:
    def __init__(self, home: Path) -> None:
        self.home = home

    def start(self, run_id: str, task_id: str, pid: int) -> None:
        with connect(self.home) as db:
            cutoff = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS)).isoformat()
            db.execute("DELETE FROM runs WHERE finished IS NOT NULL AND started < ?", (cutoff,))
            db.execute(
                "DELETE FROM runs WHERE id IN (SELECT id FROM runs WHERE finished IS NOT NULL ORDER BY started DESC LIMIT -1 OFFSET ?)",
                (MAX_RUNS - 1,),
            )
            db.execute(
                "INSERT INTO runs(id,task_id,started,status,pid) VALUES (?,?,?,?,?)",
                (run_id, task_id, datetime.now(UTC).isoformat(), "running", pid),
            )

    def append(self, run_id: str, stream: str, content: str) -> None:
        with connect(self.home) as db:
            db.execute(
                "INSERT INTO logs(run_id,stream,content) VALUES (?,?,?)", (run_id, stream, content)
            )

    def finish(
        self, run_id: str, status: str, code: int | None, duration: float, truncated: bool
    ) -> None:
        with connect(self.home) as db:
            db.execute(
                "UPDATE runs SET finished=?,status=?,exit_code=?,duration=?,truncated=? WHERE id=?",
                (datetime.now(UTC).isoformat(), status, code, duration, int(truncated), run_id),
            )

    def history(self, task_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        with connect(self.home) as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE (? IS NULL OR task_id=?) ORDER BY started DESC LIMIT ? OFFSET ?",
                (task_id, task_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def result(self, run_id: str) -> dict[str, Any]:
        with connect(self.home) as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise TickworkError("not-found", "Run does not exist")
        return dict(row)

    def logs(self, run_id: str, limit: int, after: int) -> list[dict[str, Any]]:
        self.result(run_id)
        with connect(self.home) as db:
            rows = db.execute(
                "SELECT seq,stream,content FROM logs WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after, limit),
            ).fetchall()
        return [dict(row) for row in rows]
