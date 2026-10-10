import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--help"],
        ["--version"],
        ["version"],
        ["task", "--help"],
        ["task", "create", "--help"],
        ["agent", "install", "--help"],
    ],
)
def test_json_help(arguments: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tickwork_cli.main", *arguments], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "arguments", [["bad"], ["task", "create"], ["task", "history", "--limit", "bad"], ["--bad"]]
)
def test_json_errors(arguments: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tickwork_cli.main", *arguments], capture_output=True, text=True
    )
    assert result.returncode != 0 and result.stdout == ""
    assert json.loads(result.stderr)["status"] == "error"
    assert "Traceback" not in result.stderr


def test_malformed_task_has_json_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"id":"x","argv":42,"cwd":null,"schedule":{}}')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tickwork_cli.main",
            "--home",
            str(tmp_path),
            "task",
            "create",
            "--file",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert json.loads(result.stderr)["code"] == "invalid-task"
