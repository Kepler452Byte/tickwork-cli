import json
import subprocess
import sys
from pathlib import Path

import pytest

from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.application_container import ApplicationContainer
from tickwork_cli.application_settings import ApplicationSettings
from tickwork_cli.common.process import command


@pytest.mark.parametrize("mode", ["success", "failure", "missing-executable", "timeout"])
def test_run_without_standard_streams_keeps_history_and_exit_code(
    tmp_path: Path, mode: str
) -> None:
    home = tmp_path / "home"
    container = ApplicationContainer(ApplicationSettings.load(home))
    container.initialize()

    exit_code = 0 if mode == "success" else 7
    argv = [
        sys.executable,
        "-c",
        f"import sys; assert sys.stdin.read() == ''; print('stdout'); print('stderr', file=sys.stderr); sys.exit({exit_code})",
    ]
    if mode == "missing-executable":
        argv = [str(tmp_path / "deleted-python.exe")]
    elif mode == "timeout":
        argv = [sys.executable, "-c", "import time; print('waiting', flush=True); time.sleep(20)"]
    container.task_service.repository.write(
        {
            "probe": Task(
                "probe",
                argv,
                str(tmp_path),
                {"kind": "manual"},
                1 if mode == "timeout" else 5,
            )
        }
    )
    script = """import sys
from tickwork_cli.main import app
sys.stdin = sys.stdout = sys.stderr = None
sys.argv = ['tickwork', '--home', sys.argv[1], 'task', 'run', 'probe', '--confirm']
app()
"""
    executable = (
        str(Path(sys.executable).with_name("pythonw.exe"))
        if sys.platform == "win32"
        else sys.executable
    )
    result = subprocess.run([executable, "-c", script, str(home)], capture_output=True, timeout=15)
    assert result.returncode == (0 if mode == "success" else 1), result.stderr
    assert result.stdout == result.stderr == b""
    runs = container.task_service.history("probe", 20, 0)
    expected_status = (
        "succeeded" if mode == "success" else "timeout" if mode == "timeout" else "failed"
    )
    assert runs[0]["status"] == expected_status
    if mode in {"success", "failure"}:
        assert runs[0]["exit_code"] == exit_code
    logs = container.task_service.logs(runs[0]["id"], 20, 0)["chunks"]
    assert logs
    if mode in {"success", "failure"}:
        assert "stdout" in "".join(chunk["content"] for chunk in logs)
        assert "stderr" in "".join(chunk["content"] for chunk in logs)
    if mode == "timeout":
        assert runs[0]["duration"] < 5
    container.close()


@pytest.mark.skipif(sys.platform != "win32", reason="requires real Windows console APIs")
def test_pythonw_runner_and_children_have_no_console(tmp_path: Path) -> None:
    home = tmp_path / "home 中文 space"
    container = ApplicationContainer(ApplicationSettings.load(home))
    container.initialize()

    container.task_service.repository.write(
        {
            "probe": Task(
                "probe",
                [
                    sys.executable,
                    "-c",
                    "import ctypes,json,sys; print(json.dumps({'console':ctypes.windll.kernel32.GetConsoleWindow(), 'stdin':sys.stdin.read()}))",
                ],
                str(tmp_path),
                {"kind": "manual"},
                5,
            )
        }
    )
    evidence = tmp_path / "runner.json"
    script = """import ctypes,json,sys
from pathlib import Path
from tickwork_cli.main import app
Path(sys.argv[2]).write_text(json.dumps({'console':ctypes.windll.kernel32.GetConsoleWindow(), 'streams_absent':sys.stdin is sys.stdout is sys.stderr is None}))
sys.argv = ['tickwork', '--home', sys.argv[1], 'task', 'run', 'probe', '--confirm']
app()
"""
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("pythonw.exe")),
            "-c",
            script,
            str(home),
            str(evidence),
        ],
        timeout=30,
    )
    assert result.returncode == 0
    assert json.loads(evidence.read_text()) == {"console": 0, "streams_absent": True}
    run = container.task_service.history("probe", 20, 0)[0]
    assert run["status"] == "succeeded"
    chunks = container.task_service.logs(run["id"], 20, 0)["chunks"]
    assert json.loads("".join(chunk["content"] for chunk in chunks)) == {"console": 0, "stdin": ""}
    assert (
        command(
            [
                sys.executable,
                "-c",
                "import ctypes; assert ctypes.windll.kernel32.GetConsoleWindow() == 0; print('helper-no-console')",
            ]
        ).strip()
        == "helper-no-console"
    )
    container.close()
