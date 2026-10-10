import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def test_manual_cli_has_no_native_dependency_and_returns_real_run_follow_up(tmp_path: Path) -> None:
    home = tmp_path / "manual home 中文"
    spec = tmp_path / "task.json"
    spec.write_text(
        json.dumps(
            {
                "id": "manual-command",
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys; print('failure detail',file=sys.stderr);sys.exit(7)",
                ],
                "cwd": str(tmp_path),
                "schedule": {"kind": "manual"},
                "timeout": 5,
            }
        ),
        encoding="utf-8",
    )
    environment = {**os.environ, "PATH": ""}

    def invoke(*args: str, error: bool = False) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "tickwork_cli.main", "--home", str(home), *args],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert (result.returncode != 0) == error, result.stderr
        assert not (result.stdout if error else result.stderr)
        return json.loads(result.stderr if error else result.stdout)

    created = invoke("task", "create", "--file", str(spec))
    assert created["follow_up"] == []
    created = invoke(
        "task", "create", "--file", str(spec), "--confirm", "--expected-plan", created["plan"]
    )
    assert not created["scheduler"]["deployed"]
    argv = created["follow_up"][0]["argv"]
    preview = invoke(*argv[3:])
    assert preview["status"] == "preview"
    run = invoke(*argv[3:], "--confirm", error=True)
    assert run["run"]["exit_code"] == 7
    assert len(run["follow_up"]) == 2
    for follow_up in run["follow_up"]:
        assert follow_up["argv"][1:3] == ["--home", str(home)]
        assert follow_up["argv"][-1] == run["run"]["id"]
        assert not follow_up["requires_execution_authorization"]
        response = invoke(*follow_up["argv"][3:])
        assert response["status"] == "ok"
    assert (
        invoke("task", "resume", "manual-command", error=True)["code"] == "schedule-not-applicable"
    )
    assert invoke("task", "show", "manual-command")["task"]["scheduler"]["enabled"] is False
