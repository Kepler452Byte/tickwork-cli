import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tickwork_cli.application_container import task_service

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_NATIVE_TEST") != "1", reason="requires real user scheduler"
)


def invoke(home: Path, *arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "tickwork_cli.main", "--home", str(home), *arguments],
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def mutate(home: Path, *arguments: str) -> dict[str, Any]:
    preview = invoke(home, *arguments)
    assert preview["status"] == "preview"
    return invoke(home, *arguments, "--confirm", "--expected-plan", preview["plan"])


def test_native_lifecycle_and_real_interval_trigger(tmp_path: Path) -> None:
    home = tmp_path / "home space 中文 & percent% dollar$"
    home.mkdir()
    artifact = tmp_path / "evidence.json"
    expected = 'arg with spaces 中文 & % $ " \\ end'
    spec = tmp_path / "task.json"
    spec.write_text(
        json.dumps(
            {
                "id": "native-probe",
                "argv": [
                    sys.executable,
                    "-c",
                    "import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps(sys.argv[2]),encoding='utf-8'); print('native-success')",
                    str(artifact),
                    expected,
                ],
                "cwd": str(tmp_path),
                "schedule": {"kind": "interval", "seconds": 60},
                "timeout": 10,
            }
        ),
        encoding="utf-8",
    )
    evidence: dict[str, Any] = {"platform": sys.platform, "doctor": invoke(home, "doctor")}
    try:
        created = mutate(home, "task", "create", "--file", str(spec))
        assert not created["scheduler"]["enabled"]
        run = invoke(home, "task", "run", "native-probe", "--confirm")
        assert run["run"]["status"] == "succeeded"
        assert json.loads(artifact.read_text(encoding="utf-8")) == expected
        artifact.unlink()
        resumed = mutate(home, "task", "resume", "native-probe")
        assert resumed["scheduler"]["enabled"]
        deadline = time.monotonic() + 150
        while not artifact.exists() and time.monotonic() < deadline:
            time.sleep(1)
        assert artifact.exists(), json.dumps(invoke(home, "task", "show", "native-probe"))
        assert json.loads(artifact.read_text(encoding="utf-8")) == expected
        # Wait for final DB commit after the artifact appears.
        time.sleep(1)
        history = invoke(home, "task", "history", "--task", "native-probe")
        assert len(history["runs"]) >= 2 and history["runs"][0]["status"] == "succeeded"
        evidence["runs"] = history["runs"]
        logs = invoke(home, "task", "logs", history["runs"][0]["id"])
        assert any("native-success" in chunk["content"] for chunk in logs["chunks"])
        evidence["logs"] = logs
        assert mutate(home, "task", "pause", "native-probe")["scheduler"]["enabled"] is False
        assert mutate(home, "task", "update", "--file", str(spec))["scheduler"]["enabled"] is False
        # Exercise native calendar formats without waiting for their future trigger.
        data = json.loads(spec.read_text(encoding="utf-8"))
        for schedule in (
            {"kind": "daily", "time": "23:59"},
            {"kind": "weekly", "day": "sun", "time": "23:58"},
        ):
            data["schedule"] = schedule
            spec.write_text(json.dumps(data), encoding="utf-8")
            mutate(home, "task", "update", "--file", str(spec))
            mutate(home, "task", "resume", "native-probe")
            mutate(home, "task", "pause", "native-probe")
        for path in home.glob("tickwork.db*"):
            path.unlink()
        assert len(invoke(home, "task", "list")["tasks"]) == 1
        assert invoke(home, "task", "history")["runs"] == []
        mutate(home, "task", "delete", "native-probe")
        assert invoke(home, "task", "list")["tasks"] == []
        assert not task_service(home).scheduler.state("native-probe")["deployed"]
        evidence["result"] = "passed"
    finally:
        service = task_service(home)
        service.scheduler.remove("native-probe")
        output = Path(os.getenv("NATIVE_EVIDENCE_DIR", str(tmp_path)))
        output.mkdir(parents=True, exist_ok=True)
        (output / f"native-{sys.platform}.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
