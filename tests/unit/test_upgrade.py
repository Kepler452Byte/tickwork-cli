import json
import os
import sys

import pytest

from tickwork_cli.app.system.service.upgrade_service import UpgradeService
from tickwork_cli.common import package_update_worker
from tickwork_cli.common.operation_error import OperationError
from tickwork_cli.common.package_updater import PackageUpdater


class FakeResources:
    def list_skills(self):
        return {}

    def show(self, name, relative="SKILL.md"):
        return {}

    def check(self):
        return {}

    def sync(self, confirm=False, expected_plan=None, skills_dir=None, hint_file=None):
        return {
            "version": "1.0",
            "expected_plan": "resources-plan",
            "conflicts": [],
            "operations": [],
            "write_performed": False,
        }


class FakeUpdater:
    def __init__(self):
        self.started = False

    def plan(self):
        return {"supported": True, "current_version": "1.0"}

    def start(self, plan, expected_plan):
        self.started = True
        return {"state": "scheduled"}

    def status(self, operation_id):
        return {"state": "scheduled"}


def test_upgrade_requires_unchanged_preview_and_returns_scheduled():
    updater = FakeUpdater()
    service = UpgradeService(FakeResources(), updater)
    preview = service.upgrade()
    with pytest.raises(OperationError, match="plan"):
        service.upgrade(confirm=True, expected_plan="wrong")
    assert not updater.started
    assert (
        service.upgrade(confirm=True, expected_plan=preview["expected_plan"])["state"]
        == "scheduled"
    )
    assert updater.started


def test_install_channel_detection_and_unknown_does_not_guess_pip(tmp_path, monkeypatch):
    updater = PackageUpdater("tickwork-cli", "tickwork", tmp_path / "state")

    class Distribution:
        version = "1.0"

        def read_text(self, name):
            return None

    from tickwork_cli.common import package_updater

    monkeypatch.setattr(package_updater.metadata, "distribution", lambda name: Distribution())
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "ordinary-venv"))
    plan = updater.plan()
    assert plan["manager"] == "unknown"
    assert plan["update_command"] == []
    assert not plan["supported"]
    for manager, segments in [
        ("uv-tool", ["uv", "tools", "product"]),
        ("pipx", ["pipx", "venvs", "product"]),
    ]:
        prefix = tmp_path.joinpath(*segments)
        command = (
            prefix
            / ("Scripts" if os.name == "nt" else "bin")
            / ("tickwork.exe" if os.name == "nt" else "tickwork")
        )
        command.parent.mkdir(parents=True)
        command.touch()
        if manager == "uv-tool":
            (prefix / "uv-receipt.toml").write_text(
                '[tool]\nrequirements = [{ name = "tickwork-cli" }]\n', encoding="utf-8"
            )
        else:
            (prefix / "pipx_metadata.json").write_text(
                json.dumps({"main_package": {"package": "tickwork-cli"}}),
                encoding="utf-8",
            )
        monkeypatch.setattr(sys, "prefix", str(prefix))
        monkeypatch.setattr(package_updater.shutil, "which", lambda name: str(tmp_path / name))
        plan = updater.plan()
        assert plan["manager"] == manager
        assert plan["supported"]
        assert plan["update_command"][-1] == ("tickwork-cli" if manager == "uv-tool" else "product")


def make_job(tmp_path, exit_code=0):
    folder = tmp_path / "path with spaces"
    folder.mkdir()
    path = folder / "result.json"
    job = {
        "operation_id": "a" * 32,
        "state": "scheduled",
        "package_stage": "pending",
        "resource_stage": "pending",
        "package": "tickwork-cli",
        "current_version": "1.0",
        "update_command": [sys.executable, "-c", f"raise SystemExit({exit_code})"],
        "entry_point": "new-cli",
        "host_pid": os.getpid(),
        "home": str(tmp_path),
    }
    path.write_text(json.dumps(job), encoding="utf-8")
    return path


def test_failed_package_update_never_runs_resource_alignment(tmp_path, monkeypatch):
    path = make_job(tmp_path, 1)
    monkeypatch.setattr(
        package_update_worker, "invoke", lambda argv: pytest.fail("Resource command must not run")
    )
    package_update_worker.run(path, wait=False)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert result["package_stage"] == "failed"
    assert result["resource_stage"] == "skipped"


def test_resource_failure_is_distinct_from_verified_package(tmp_path, monkeypatch):
    path = make_job(tmp_path)

    def invoke(argv):
        if "--version" in argv:
            return {"package": "tickwork-cli", "version": "1.1"}
        raise RuntimeError("Conflict")

    monkeypatch.setattr(package_update_worker, "invoke", invoke)
    package_update_worker.run(path, wait=False)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert result["package_stage"] == "completed"
    assert result["resource_stage"] == "failed"


def test_success_requires_post_alignment_verification(tmp_path, monkeypatch):
    path = make_job(tmp_path)

    def invoke(argv):
        if "--version" in argv:
            return {"package": "tickwork-cli", "version": "1.1"}
        return {
            "package": "tickwork-cli",
            "version": "1.1",
            "expected_plan": "plan",
            "operations": [],
            "conflicts": [],
        }

    monkeypatch.setattr(package_update_worker, "invoke", invoke)
    package_update_worker.run(path, wait=False)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["state"] == "completed"
    assert result["package_stage"] == result["resource_stage"] == "completed"


def test_spawn_failure_is_a_durable_failure_and_stdout_is_clean(tmp_path, monkeypatch, capsys):
    updater = PackageUpdater("tickwork-cli", "tickwork", tmp_path / "state")
    from tickwork_cli.common import package_updater

    def fail(*args, **kwargs):
        raise OSError("Cannot spawn")

    monkeypatch.setattr(package_updater.subprocess, "Popen", fail)
    with pytest.raises(OperationError, match="Unable to start"):
        updater.start(
            {
                "current_version": "1.0",
                "update_command": ["uv", "tool", "upgrade", "tickwork-cli"],
                "entry_point": "tickwork",
            },
            "plan",
        )
    assert capsys.readouterr().out == ""
    operation = next((tmp_path / "state/upgrades").iterdir()).name
    assert updater.status(operation)["state"] == "failed"


def test_result_query_does_not_create_state_or_accept_path_traversal(tmp_path):
    updater = PackageUpdater("tickwork-cli", "tickwork", tmp_path / "state")
    with pytest.raises(OperationError, match="Invalid"):
        updater.status("../../other")
    with pytest.raises(OperationError, match="does not exist"):
        updater.status("a" * 32)
    assert not updater.state_root.exists()


def test_new_cli_malformed_output_and_nonzero_exit_are_failures(tmp_path):
    with pytest.raises(ValueError):
        package_update_worker.invoke([sys.executable, "-c", "print('not json')"])
    with pytest.raises(RuntimeError):
        package_update_worker.invoke([sys.executable, "-c", "raise SystemExit(2)"])


def test_post_alignment_pending_changes_are_failure(tmp_path, monkeypatch):
    path = make_job(tmp_path)
    count = 0

    def invoke(argv):
        nonlocal count
        if "--version" in argv:
            return {"version": "1.1"}
        count += 1
        return {
            "package": "tickwork-cli",
            "version": "1.1",
            "expected_plan": "plan",
            "operations": [{"action": "update"}] if count == 3 else [],
            "conflicts": [],
        }

    monkeypatch.setattr(package_update_worker, "invoke", invoke)
    package_update_worker.run(path, wait=False)
    result = json.loads(path.read_text())
    assert result["state"] == "failed"
    assert result["package_stage"] == "completed" and result["resource_stage"] == "failed"
