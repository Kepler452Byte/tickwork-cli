import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tickwork_cli.common.package_updater import PackageUpdater


@pytest.mark.parametrize("exit_code", [0, 1])
def test_detached_update_waits_then_verifies_resources(tmp_path: Path, exit_code: int) -> None:
    home = tmp_path / "upgrade home 中文 & ' $"
    artifact = tmp_path / "package ' $ result.json"
    entry = Path(sys.executable).parent / ("tickwork.exe" if os.name == "nt" else "tickwork")
    launcher = """import json,sys,time
from pathlib import Path
from tickwork_cli.common.package_updater import PackageUpdater
home=Path(sys.argv[1]); artifact=Path(sys.argv[2])
update=[sys.executable,'-c',"import ctypes,sys;from pathlib import Path; console=ctypes.windll.kernel32.GetConsoleWindow() if sys.platform=='win32' else 0;assert not console;Path(sys.argv[1]).write_text('updated');raise SystemExit(int(sys.argv[2]))",str(artifact),sys.argv[4]]
result=PackageUpdater('tickwork-cli','tickwork',home).start({'current_version':'0.2.2','update_command':update,'entry_point':sys.argv[3]},'test-plan')
print(json.dumps(result))
time.sleep(1)
assert not artifact.exists(), 'Updater ran before CLI exited'
"""
    host = subprocess.run(
        [sys.executable, "-c", launcher, str(home), str(artifact), str(entry), str(exit_code)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert host.returncode == 0, host.stderr
    assert host.stderr == ""
    scheduled = json.loads(host.stdout)
    assert scheduled["state"] == "scheduled"
    updater = PackageUpdater("tickwork-cli", "tickwork", home)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        payload = updater.status(scheduled["operation_id"])
        if payload["state"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    output = os.getenv("NATIVE_EVIDENCE_DIR")
    if output:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"upgrade-{sys.platform}-{exit_code}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    assert payload["state"] == ("failed" if exit_code else "completed"), (
        json.dumps(payload),
        Path(scheduled["log_path"]).read_text(encoding="utf-8"),
    )
    assert payload["package_stage"] == ("failed" if exit_code else "completed")
    assert payload["resource_stage"] == ("skipped" if exit_code else "completed")
    assert artifact.read_text() == "updated"
    assert not (home / "tasks.yaml").exists()
    assert not (home / "tickwork.db").exists()
