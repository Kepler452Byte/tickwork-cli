import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from tickwork_cli.app.task.cli.task_cli import (
    execute_task,
    register_task_commands,
)
from tickwork_cli.application_container import ApplicationContainer
from tickwork_cli.application_settings import ApplicationSettings
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.cli_output import write_result
from tickwork_cli.app.agent_resources.cli.agent_resource_cli import (
    execute_agent,
    register_agent_commands,
)
from tickwork_cli.app.system.cli.system_cli import execute_system, register_system_commands, version


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
                        "type": "boolean"
                        if action.nargs == 0
                        else getattr(action.type, "__name__", "string"),
                        "nargs": action.nargs,
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
        default=None,
        help="Local state directory (default TICKWORK_HOME or ~/.tickwork)",
    )
    root.add_argument("--version", action="store_true", help="Report installed version as JSON")
    commands = root.add_subparsers(dest="command")
    register_system_commands(commands)
    commands.add_parser(
        "doctor", description="Check native scheduler and user session; do not change host settings"
    )
    task = commands.add_parser(
        "task", description="Manage local task definitions, deployment, runs and logs"
    )
    register_task_commands(task)
    register_agent_commands(commands)
    return root


def app() -> None:
    container: ApplicationContainer | None = None
    try:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        root = parser()
        args = root.parse_args()
        if args.version or args.command == "version":
            write_result(version())
            return
        if args.command is None:
            print(root.format_help(), end="")
            return
        container = ApplicationContainer(ApplicationSettings.load(args.home))
        container.initialize()
        if args.command in {"agent", "skill"}:
            result = execute_agent(args, container)
        elif args.command == "upgrade":
            result = execute_system(args, container)
        elif args.command == "doctor":
            result = {"home": str(container.settings.home), **container.scheduler.doctor()}
        else:
            result = execute_task(args, container.task_service)
        status = str(result.pop("status", "ok"))
        write_result(result, status=status, error=status == "error")
        if status == "error":
            raise SystemExit(1)
    except TickworkError as exc:
        write_result({"code": exc.code, "message": str(exc)}, status="error", error=True)
        raise SystemExit(getattr(exc, "exit_code", 1)) from None
    except (OSError, ValueError) as exc:
        write_result({"code": "invalid-input", "message": str(exc)}, status="error", error=True)
        raise SystemExit(1) from None
    except Exception:
        write_result(
            {
                "code": "operation-failed",
                "message": "Unexpected failure; inspect local state and retry",
            },
            status="error",
            error=True,
        )
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        write_result(
            {"code": "interrupted", "message": "Execution interrupted"}, status="error", error=True
        )
        raise SystemExit(130) from None
    finally:
        if container is not None:
            container.close()


if __name__ == "__main__":
    app()
