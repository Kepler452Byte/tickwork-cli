import json
import os
import subprocess
import sys
import time
from pathlib import Path


def test_detached_update_waits_then_aligns_resources(tmp_path: Path) -> None:
    home = tmp_path / "upgrade home 中文 & ' $"
    artifact = tmp_path / "package ' $ result.json"
    launcher = """import sys,time
from pathlib import Path
from tickwork_cli.common.package_update import spawn_update
home=Path(sys.argv[1]); artifact=Path(sys.argv[2])
update=[sys.executable,'-c',"import sys;from pathlib import Path;Path(sys.argv[1]).write_text('updated')",str(artifact)]
spawn_update(update,home)
time.sleep(1)
assert not artifact.exists(), 'Updater ran before CLI exited'
"""
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(home), str(artifact)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""
    log = home / "upgrade.log"
    deadline = time.monotonic() + 30
    payload = None
    while time.monotonic() < deadline:
        try:
            payload = json.loads(log.read_text(encoding="utf-8-sig"))
            break
        except (OSError, ValueError):
            time.sleep(0.2)
    assert payload is not None, log.read_text(encoding="utf-8-sig") if log.exists() else "no log"
    assert artifact.read_text() == "updated"
    assert payload["status"] == "ok" and not payload["tasks_changed"]
    assert payload["resources"]["skipped"] == ["agent-resources-not-registered"]
    assert not (home / "tasks.yaml").exists()
    output = os.getenv("NATIVE_EVIDENCE_DIR")
    if output:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"upgrade-{sys.platform}.json").write_text(json.dumps(payload), encoding="utf-8")
