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
        capture_output=True,
        check=True,
    )
    with (root / "pyproject.toml").open("rb") as handle:
        expected_version = tomllib.load(handle)["project"]["version"]
    assert json.loads(result.stdout) == {"status": "ok", "version": expected_version}
