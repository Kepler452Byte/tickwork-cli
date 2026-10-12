import argparse
from pathlib import Path
from typing import Any

from tickwork_cli.application_container import ApplicationContainer
from tickwork_cli.common.application_errors import TickworkError


def register_agent_commands(commands: Any) -> None:
    agent = commands.add_parser(
        "agent", description="Install/sync explicitly registered package resources"
    )
    actions = agent.add_subparsers(dest="agent_action")
    for name in ("install", "sync"):
        child = actions.add_parser(name)
        if name == "install":
            child.add_argument("--hint-file", "--agents-file", dest="hint_file", type=Path)
            child.add_argument("--skills-dir", type=Path)
        child.add_argument("--confirm", action="store_true")
        child.add_argument("--expected-plan")
    status = actions.add_parser("upgrade-status")
    status.add_argument("operation_id")
    skill = commands.add_parser("skill", description="Inspect packaged Skills without installing")
    actions = skill.add_subparsers(dest="skill_action")
    actions.add_parser("list")
    actions.add_parser("check")
    show = actions.add_parser("show")
    show.add_argument("name")
    show.add_argument("--file", default="SKILL.md")


def execute_agent(args: argparse.Namespace, container: ApplicationContainer) -> dict[str, object]:
    resources = container.agent_service
    if args.command == "skill":
        if args.skill_action == "list":
            return resources.list_skills()
        if args.skill_action == "check":
            return resources.check()
        if args.skill_action == "show":
            return resources.show(args.name, args.file)
    elif args.agent_action in {"install", "sync"}:
        result = (
            resources.install(args.skills_dir, args.hint_file, args.confirm, args.expected_plan)
            if args.agent_action == "install"
            else resources.sync(args.confirm, args.expected_plan)
        )
        return {"status": "ok" if args.confirm else "preview", **result}
    elif args.agent_action == "upgrade-status":
        result = container.upgrade_service.status(args.operation_id)
        if result["state"] == "failed":
            return {"status": "error", "code": "upgrade-failed", **result}
        return result
    raise TickworkError("invalid-command", "Use agent --help or skill --help")
