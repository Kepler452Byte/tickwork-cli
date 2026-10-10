import json
import subprocess
import sys
from pathlib import Path

import pytest

from tickwork_cli.app.agent.service.agent_resource_service import AgentResourceService
from tickwork_cli.app.upgrade.service.upgrade_service import UpgradeService
from tickwork_cli.common import package_update
from tickwork_cli.common.application_errors import TickworkError


def test_upgrade_aligns_registered_resources_without_touching_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = tmp_path / "AGENTS.md"
    skills = tmp_path / "skills"
    agents.write_text("User-owned instructions\n", encoding="utf-8")
    resources = AgentResourceService(tmp_path)
    preview = resources.install(agents, skills, False, None)
    assert not (tmp_path / "local.yaml").exists()
    resources.install(agents, skills, True, preview["plan"])
    # Installed destinations are unique even after repeated alignment.
    preview = resources.install(agents, skills, False, None)
    resources.install(agents, skills, True, preview["plan"])
    before = (tmp_path / "local.yaml").read_bytes()
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text("tasks: []\n# User-owned state\n", encoding="utf-8")
    tasks_before = tasks.read_bytes()
    monkeypatch.setattr(package_update, "latest_version", lambda: None)
    monkeypatch.setattr(package_update, "update_command", lambda: ("editable", None))
    result = UpgradeService(tmp_path, resources).upgrade()
    assert result["package"]["action"] == "skipped"
    assert len(result["resources"]["targets"]) == 1
    assert agents.read_text(encoding="utf-8").startswith("User-owned instructions\n")
    assert before == (tmp_path / "local.yaml").read_bytes()
    assert tasks_before == tasks.read_bytes()
    assert not (tmp_path / "tickwork.db").exists()
    (skills / "tickwork-task-management/SKILL.md").write_text("User edit", encoding="utf-8")
    with pytest.raises(TickworkError, match="locally edited"):
        UpgradeService(tmp_path, resources).upgrade(skip_package=True)


def test_upgrade_defers_resources_until_updated_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(package_update, "latest_version", lambda: "9.0.0")
    command = ["uv", "tool", "upgrade", "tickwork-cli"]
    monkeypatch.setattr(package_update, "update_command", lambda: ("uv-tool", command))
    observed = []
    monkeypatch.setattr(
        package_update,
        "spawn_update",
        lambda update, home: observed.append((update, home)) or home / "upgrade.log",
    )
    resources = AgentResourceService(tmp_path)
    monkeypatch.setattr(
        resources, "align", lambda: pytest.fail("Resources must be aligned by the new package")
    )
    result = UpgradeService(tmp_path, resources).upgrade()
    assert result["resources"] == "deferred"
    assert result["package"]["action"] == "updater-spawned"
    assert observed == [(command, tmp_path)]
    assert not result["tasks_changed"]


def test_skip_package_is_hidden_and_does_not_query_pypi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        package_update,
        "latest_version",
        lambda: pytest.fail("Internal alignment must not query PyPI"),
    )
    result = UpgradeService(tmp_path, AgentResourceService(tmp_path)).upgrade(True)
    assert result["resources"]["skipped"] == ["agent-resources-not-registered"]
    response = subprocess.run(
        [sys.executable, "-m", "tickwork_cli.main", "upgrade", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "skip-package" not in response.stdout
    assert json.loads(response.stdout)["status"] == "ok"


def test_shell_updater_quotes_paths_and_waits_for_parent(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX shell test")
    artifact = tmp_path / "artifact ' 中文 $name.json"
    update = [
        sys.executable,
        "-c",
        "import sys;from pathlib import Path;Path(sys.argv[1]).write_text('updated')",
        str(artifact),
    ]
    align = [
        sys.executable,
        "-c",
        "import sys;from pathlib import Path;p=Path(sys.argv[1]);p.write_text(p.read_text()+' aligned')",
        str(artifact),
    ]
    script = package_update.updater_script(update, align, 99999999, False)
    subprocess.run(["/bin/sh", "-c", script], check=True, timeout=15)
    assert artifact.read_text() == "updated aligned"
    windows = package_update.updater_script(
        ["tool ' 中文", "arg ' $x"], ["tickwork", "upgrade"], 123, True
    )
    assert "Get-Process -Id 123" in windows
    assert "'tool '' 中文'" in windows and "if ($LASTEXITCODE -eq 0)" in windows
