import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("RUN_WHEEL_TEST") != "1", reason="release-only wheel check")
def test_wheel_installs_and_runs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=root, check=True)
    environment = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(environment)], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next(wheel_dir.glob("*.whl"))
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True)
    result = subprocess.run(
        [str(python), "-m", "tickwork_cli.main", "version"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    with (root / "pyproject.toml").open("rb") as handle:
        expected_version = tomllib.load(handle)["project"]["version"]
    assert json.loads(result.stdout) == {"status": "ok", "version": expected_version}

    for arguments in ([], ["--help"], ["task", "--help"], ["task", "create", "--help"]):
        response = subprocess.run(
            [str(python), "-m", "tickwork_cli.main", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        assert json.loads(response.stdout)["status"] == "ok" and response.stderr == ""
    error = subprocess.run(
        [str(python), "-m", "tickwork_cli.main", "invalid-command"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert error.returncode != 0 and error.stdout == ""
    assert json.loads(error.stderr)["status"] == "error"
    command = [
        str(python),
        "-m",
        "tickwork_cli.main",
        "--home",
        str(tmp_path / "home"),
        "agent",
        "install",
        "--agents-file",
        str(tmp_path / "AGENTS.md"),
        "--skills-dir",
        str(tmp_path / "skills"),
    ]
    preview = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    subprocess.run(
        [*command, "--confirm", "--expected-plan", preview["plan"]], capture_output=True, check=True
    )
    assert (tmp_path / "skills/tickwork-task-management/SKILL.md").exists()
    assert (tmp_path / "skills/tickwork-task-management/references/platform-notes.md").exists()
    assert not (tmp_path / "home/tasks.yaml").exists()
