"""Coordinate package replacement, version verification and resource alignment."""

import hashlib
import json

from tickwork_cli.app.agent_resources.interface.public.agent_resource_sync import IAgentResourceSync
from tickwork_cli.app.system.interface.package_updater import IPackageUpdater
from tickwork_cli.common.operation_error import OperationError


class UpgradeService:
    def __init__(self, resources: IAgentResourceSync, updater: IPackageUpdater):
        self.resources = resources
        self.updater = updater

    def upgrade(
        self, skip_package: bool = False, confirm: bool = False, expected_plan: str | None = None
    ) -> dict[str, object]:
        if skip_package:
            return self.resources.sync(confirm, expected_plan)
        package = self.updater.plan()
        resources = self.resources.sync()
        plan: dict[str, object] = {"package": package, "resources": resources}
        signature = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        plan["expected_plan"] = signature
        if not confirm:
            return plan
        if expected_plan != signature:
            raise OperationError(
                "Upgrade plan changed or --expected-plan is missing; preview again", "plan-conflict"
            )
        if not package["supported"]:
            raise OperationError(str(package["hint"]), "unsupported-installation", 2)
        if resources["conflicts"]:
            raise OperationError(
                "Resolve Agent resource conflicts before updating the package", "resource-conflict"
            )
        return self.updater.start(package, signature)

    def status(self, operation_id: str) -> dict[str, object]:
        return self.updater.status(operation_id)
