import argparse
import json
import os
import sys
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import NoReturn

from tickwork_cli.app.agent.service.agent_resource_service import install_resources
from tickwork_cli.app.task.cli.task_cli import (
    execute_task,
    mutation_options,
    register_task_commands,
)
from tickwork_cli.application_container import task_service
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.cli_output import write_result


class JsonParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        options = []
        commands = []
        for action in self._actions:
            if action.help == argparse.SUPPRESS:
                continue
            if isinstance(action, argparse._SubParsersAction):
                commands = [
                    {
                        "name": name,
                        "description": parser.description or parser.format_usage().strip(),
                    }
                    for name, parser in action.choices.items()
                ]
            else:
                options.append(
                    {
                        "names": action.option_strings or [action.dest],
                        "required": action.required,
                        "description": action.help,
                        "default": action.default,
                        "choices": action.choices,
                    }
                )
        return (
            json.dumps(
                {
                    "status": "ok",
                    "command": self.prog,
                    "description": self.description,
                    "options": options,
                    "commands": commands,
                    "notes": self.epilog,
                },
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )

    def error(self, message: str) -> NoReturn:
        raise TickworkError("invalid-arguments", message)


def parser() -> JsonParser:
    root = JsonParser(
        prog="tickwork",
        description="Device-local native scheduled tasks. JSON output; no daemon or cloud.",
    )
    root.add_argument(
        "--home",
        type=Path,
        default=Path(os.getenv("TICKWORK_HOME", str(Path.home() / ".tickwork"))),
        help="Local state directory (default TICKWORK_HOME or ~/.tickwork)",
    )
    root.add_argument("--version", action="store_true", help="Report installed version as JSON")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("version", description="Report installed package version")
    commands.add_parser(
        "doctor", description="Check native scheduler and user session; do not change host settings"
    )
    task = commands.add_parser(
        "task", description="Manage local task definitions, deployment, runs and logs"
    )
    register_task_commands(task)
    agent = commands.add_parser("agent", description="Explicitly install packaged Agent resources")
    sub = agent.add_subparsers(dest="agent_action")
    install = sub.add_parser(
        "install", description="Align owned Hint block and Skill; never enables tasks"
    )
    install.add_argument("--agents-file", type=Path, required=True)
    install.add_argument("--skills-dir", type=Path, required=True)
    mutation_options(install)
    return root


def app() -> None:
    try:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        root = parser()
        args = root.parse_args()
        if args.version or args.command == "version":
            write_result({"version": installed_version("tickwork-cli")})
            return
        if args.command is None:
            print(root.format_help(), end="")
            return
        home = args.home.expanduser().resolve()
        if args.command == "agent":
            if args.agent_action != "install":
                raise TickworkError("invalid-command", "Use agent --help")
            result = install_resources(
                args.agents_file.expanduser().resolve(),
                args.skills_dir.expanduser().resolve(),
                home,
                args.confirm,
                args.expected_plan,
            )
        elif args.command == "doctor":
            result = {"home": str(home), **task_service(home).scheduler.doctor()}
        else:
            result = execute_task(args, task_service(home))
        status = str(result.pop("status", "ok"))
        write_result(result, status=status, error=status == "error")
        if status == "error":
            raise SystemExit(1)
    except TickworkError as exc:
        write_result({"code": exc.code, "message": str(exc)}, status="error", error=True)
        raise SystemExit(1) from None
    except (OSError, ValueError) as exc:
        write_result({"code": "invalid-input", "message": str(exc)}, status="error", error=True)
        raise SystemExit(1) from None
    except Exception as exc:
        write_result({"code": "operation-failed", "message": str(exc)}, status="error", error=True)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        write_result(
            {"code": "interrupted", "message": "Execution interrupted"}, status="error", error=True
        )
        raise SystemExit(130) from None


if __name__ == "__main__":
    app()
