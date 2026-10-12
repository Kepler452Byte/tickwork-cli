import json
import subprocess
import sys

import pytest


def call(home, *args):
    return subprocess.run(
        [sys.executable, "-m", "tickwork_cli.main", "--home", str(home), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--version"],
        ["version"],
        ["--help"],
        ["skill", "--help"],
        ["skill", "show", "--help"],
        ["agent", "--help"],
        ["upgrade", "--help"],
        ["skill", "list"],
        ["skill", "check"],
        ["upgrade"],
        ["upgrade", "--skip-package"],
    ],
)
def test_queries_are_json_without_state_writes(tmp_path, args):
    home = tmp_path / "home"
    result = call(home, *args)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["status"] in {"ok", "preview"}
    assert not home.exists()


def test_editable_upgrade_rejects_package_confirmation(tmp_path):
    home = tmp_path / "home"
    preview = json.loads(call(home, "upgrade").stdout)
    assert preview["package"]["manager"] == "editable"
    result = call(home, "upgrade", "--confirm", "--expected-plan", preview["expected_plan"])
    assert result.returncode == 2 and result.stdout == ""
    assert json.loads(result.stderr)["code"] == "unsupported-installation"
    assert not home.exists()


def test_skill_reference_and_hint_only_confirm_contract(tmp_path):
    home = tmp_path / "home"
    shown = call(
        home, "skill", "show", "tickwork-task-management", "--file", "references/platform-notes.md"
    )
    assert json.loads(shown.stdout)["content"]
    args = ["agent", "install", "--hint-file", str(tmp_path / "hint.md")]
    assert call(home, *args, "--confirm").returncode != 0
    assert not home.exists()
    preview = json.loads(call(home, *args).stdout)
    applied = call(home, *args, "--expected-plan", preview["expected_plan"], "--confirm")
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["write_performed"]
    synced = json.loads(call(home, "agent", "sync").stdout)
    assert synced["operations"] == []
    assert not (home / "tickwork.db").exists()
    assert not (home / "tasks.yaml").exists()
