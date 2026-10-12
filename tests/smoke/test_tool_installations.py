import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_WHEEL_TEST") != "1",
    reason="Release tool installation check",
)
@pytest.mark.parametrize("manager", ["uv", "pipx"])
def test_installed_tools_upgrade_and_use_own_environment(tmp_path: Path, manager: str) -> None:
    root = Path(__file__).resolve().parents[2]
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=root, check=True)
    wheel = next(dist.glob("*.whl"))
    home = tmp_path / "tools 中文 space"
    env = {**os.environ, "UV_TOOL_DIR": str(home), "UV_TOOL_BIN_DIR": str(tmp_path / "bin")}
    if manager == "uv":
        subprocess.run(
            ["uv", "tool", "install", "--python", sys.executable, str(wheel)], env=env, check=True
        )
        prefix = home / "tickwork-cli"
    else:
        installer = tmp_path / "installer"
        subprocess.run(["uv", "venv", str(installer)], check=True)
        python = installer / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(["uv", "pip", "install", "--python", str(python), "pipx"], check=True)
        env.update(PIPX_HOME=str(home), PIPX_BIN_DIR=str(tmp_path / "bin"))
        env["PATH"] = str(python.parent) + os.pathsep + env["PATH"]
        subprocess.run(
            [str(python), "-m", "pipx", "install", "--python", sys.executable, str(wheel)],
            env=env,
            check=True,
        )
        prefix = home / "venvs/tickwork-cli"
    entry = prefix / ("Scripts/tickwork.exe" if os.name == "nt" else "bin/tickwork")
    state = tmp_path / "state"
    args = [str(entry), "--home", str(state), "upgrade"]
    preview = json.loads(subprocess.check_output(args, env=env, text=True, encoding="utf-8"))
    assert preview["package"]["manager"] == ("uv-tool" if manager == "uv" else "pipx")
    assert preview["package"]["supported"]
    scheduled = json.loads(
        subprocess.check_output(
            [*args, "--confirm", "--expected-plan", preview["expected_plan"]],
            env=env,
            text=True,
            encoding="utf-8",
        )
    )
    query = [str(entry), "--home", str(state), "agent", "upgrade-status", scheduled["operation_id"]]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        # During environment replacement the entry point can be temporarily absent.
        try:
            probe = subprocess.run(query, env=env, capture_output=True, text=True, encoding="utf-8")
            result = json.loads(probe.stdout or probe.stderr)
        except (OSError, ValueError):
            time.sleep(0.2)
            continue
        if result.get("state") in {"completed", "failed"}:
            break
        time.sleep(0.2)
    assert result["state"] == "completed", (result, Path(scheduled["log_path"]).read_text())
    assert result["package_stage"] == result["resource_stage"] == "completed"
    assert not (state / "tickwork.db").exists()
    if sys.platform != "win32":
        return
    output = tmp_path / "probe.json"
    script = """import ctypes,json,sys
from importlib.metadata import version
from pathlib import Path
from tickwork_cli.app.task.adapter.windows_scheduler import WindowsScheduler, NS
from tickwork_cli.app.task.schema.task_schema import Task
import xml.etree.ElementTree as ET
t = Task('probe', [sys.executable, '-c', 'pass'], str(Path.cwd()), {'kind':'interval','seconds':60})
xml = ET.fromstring(WindowsScheduler(Path.cwd()).xml(t, False, 'S-1-test'))
Path(sys.argv[1]).write_text(json.dumps({'version':version('tickwork-cli'), 'prefix':sys.prefix, 'console':ctypes.windll.kernel32.GetConsoleWindow(), 'command':xml.findtext(f'{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Command')}))
"""
    pythonw = prefix / "Scripts/pythonw.exe"
    subprocess.run([str(pythonw), "-c", script, str(output)], timeout=30, check=True)
    result = json.loads(output.read_text())
    import tomllib

    assert (
        result["version"]
        == tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    )
    assert Path(result["prefix"]).resolve() == prefix.resolve()
    assert result["console"] == 0
    assert Path(result["command"]).resolve() == pythonw.resolve()
