import sys
from pathlib import Path

import pytest

from tickwork_cli.app.task.schema.task_schema import Task


@pytest.fixture
def task(tmp_path: Path) -> Task:
    return Task(
        "example",
        [sys.executable, "-c", "print('hello')"],
        str(tmp_path),
        {"kind": "interval", "seconds": 60},
        5,
    )
