import argparse
import json
from pathlib import Path
from typing import Any

from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.app.task.service.task_service import TaskService
from tickwork_cli.common.application_errors import TickworkError


def mutation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirm", action="store_true", help="Apply the previewed operation")
    parser.add_argument("--expected-plan", help="Hash returned by the current preview")


def register_task_commands(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="action")
    for name in ("create", "update"):
        child = commands.add_parser(
            name, help=f"{name.title()} a task from a JSON file; preview by default"
        )
        child.add_argument(
            "--file",
            required=True,
            type=Path,
            help="JSON task: id, argv array, cwd, schedule, timeout",
        )
        mutation_options(child)
    commands.add_parser("list", help="List definitions and actual native scheduler state")
    for name in ("show", "pause", "resume", "delete", "run"):
        child = commands.add_parser(name, help=f"{name.title()} a local task")
        child.add_argument("id")
        if name != "show":
            mutation_options(child)
        if name == "run":
            child.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    history = commands.add_parser(
        "history", help="Paginated run history; lost historical logs are not recoverable"
    )
    history.add_argument("--task")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--offset", type=int, default=0)
    result = commands.add_parser(
        "result", help="Get one run result; process success is not artifact verification"
    )
    result.add_argument("run_id")
    logs = commands.add_parser(
        "logs", help="Paginated UTF-8 logs, invalid bytes replaced; cursor is last seq"
    )
    logs.add_argument("run_id")
    logs.add_argument("--limit", type=int, default=20)
    logs.add_argument("--after", type=int, default=0)
    parser.epilog = 'Task JSON: {"id":"example","argv":["/absolute/executable","arg"],"cwd":"/absolute/directory","schedule":{"kind":"interval","seconds":300},"timeout":3600}. Schedule alternatives: {"kind":"manual"} (no native deployment), {"kind":"daily","time":"09:00"}, {"kind":"weekly","day":"mon","time":"09:00"}. All times are device local; intervals use whole minutes 60..86400 seconds.'


def execute_task(args: argparse.Namespace, service: TaskService) -> dict[str, Any]:
    action = args.action
    if action in {"create", "update"}:
        task = Task.parse(json.loads(args.file.read_text(encoding="utf-8")))
        return service.change(action, task.id, task, args.confirm, args.expected_plan)
    if action in {"pause", "resume", "delete"}:
        return service.change(action, args.id, None, args.confirm, args.expected_plan)
    if action == "list":
        return {"tasks": service.list_tasks()}
    if action == "show":
        return {"task": service.show(args.id)}
    if action == "run":
        result = service.run(args.id, args.confirm, args.scheduled)
        follow_up = service.run_follow_up(result["id"]) if "id" in result else []
        if result.get("status") in {"failed", "timeout", "interrupted"}:
            return {
                "status": "error",
                "code": "run-failed",
                "message": "Task process did not succeed",
                "run": result,
                "follow_up": follow_up,
            }
        if result.get("status") == "preview":
            return result
        return {"run": result, "follow_up": follow_up}
    repository = service
    if action == "history":
        return {"runs": repository.history(args.task, args.limit, args.offset)}
    if action == "result":
        return {"run": repository.result(args.run_id)}
    if action == "logs":
        return service.logs(args.run_id, args.limit, args.after)
    raise TickworkError("invalid-command", "Use task --help to discover commands")
