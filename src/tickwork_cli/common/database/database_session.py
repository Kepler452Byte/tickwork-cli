import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DatabaseSession:
    """Own one lazy SQLite connection and its transaction lifecycle."""

    def __init__(self, path: Path):
        self.path = path
        self.connection: sqlite3.Connection | None = None
        self.schema = ""

    def initialize(self, schema: str) -> None:
        self.schema = schema

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=15)
            try:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA foreign_keys=ON")
                db.executescript(self.schema)
            except BaseException:
                db.close()
                raise
            self.connection = db
        with self.connection:
            yield self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
