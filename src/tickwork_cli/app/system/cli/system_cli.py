import argparse
from importlib.metadata import version as installed_version
from typing import Any

from tickwork_cli.application_container import ApplicationContainer


def version() -> dict[str, object]:
    return {"version": installed_version("tickwork-cli")}


def register_system_commands(commands: Any) -> None:
    commands.add_parser("version", description="Report installed package version")
    upgrade = commands.add_parser(
        "upgrade", description="Preview package update and resource alignment"
    )
    upgrade.add_argument(
        "--skip-package", action="store_true", help="Offline registered resource alignment"
    )
    upgrade.add_argument("--confirm", action="store_true")
    upgrade.add_argument("--expected-plan")


def execute_system(args: argparse.Namespace, container: ApplicationContainer) -> dict[str, object]:
    result = container.upgrade_service.upgrade(args.skip_package, args.confirm, args.expected_plan)
    return {"status": "ok" if args.confirm else "preview", **result}
