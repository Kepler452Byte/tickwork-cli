import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(home: Path) -> Iterator[sqlite3.Connection]:
    home.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home / "tickwork.db", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
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
    """)
    try:
        with db:
            yield db
    finally:
        db.close()
