from importlib.metadata import version
from pathlib import Path
from typing import Any

from tickwork_cli.app.agent.service.agent_resource_service import AgentResourceService
from tickwork_cli.common import package_update


class UpgradeService:
    def __init__(self, home: Path, resources: AgentResourceService):
        self.home = home
        self.resources = resources

    def upgrade(self, skip_package: bool = False) -> dict[str, Any]:
        installed = version("tickwork-cli")
        latest = None if skip_package else package_update.latest_version()
        manager, command = package_update.update_command()
        package: dict[str, Any] = {"installed": installed, "latest": latest, "manager": manager}
        if not skip_package and command is not None and package_update.newer(latest, installed):
            log = package_update.spawn_update(command, self.home)
            return {
                "status": "ok",
                "package": {**package, "action": "updater-spawned"},
                "resources": "deferred",
                "log_path": str(log),
                "follow_up": [
                    {
                        "argv": ["tickwork", "version"],
                        "reason": "Wait for the updater to finish, then verify package version and upgrade.log",
                        "requires_execution_authorization": False,
                    }
                ],
                "tasks_changed": False,
            }
        action = "skipped" if skip_package or command is None or latest is None else "up-to-date"
        hint = (
            "Update through the original installation channel; only registered Agent resources were aligned"
            if command is None
            else "PyPI unavailable; retry upgrade when online"
            if latest is None and not skip_package
            else None
        )
        return {
            "status": "ok",
            "package": {**package, "action": action, "hint": hint},
            "resources": self.resources.align(),
            "tasks_changed": False,
            "follow_up": [],
        }
