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
    cleanup = commands.add_parser(
        "cleanup", help="Preview completed history/log removal; running records excluded"
    )
    cleanup.epilog = "Defaults per task: success 7 days/100 runs; failed, timeout and interrupted 30 days/100 runs, retaining at least 10 failures. Count caps override the minimum; age uses finished UTC. TICKWORK_SUCCESS_DAYS, TICKWORK_FAILURE_DAYS, TICKWORK_SUCCESS_LIMIT, TICKWORK_FAILURE_LIMIT, TICKWORK_FAILURE_KEEP override defaults. An explicit --older-than overrides the default policy; use --keep-failures to preserve all failures. Deletion cascades logs; compact separately to reclaim disk. Confirmation also marks unlocked orphan running rows interrupted, retaining them for a subsequent cleanup."
    cleanup.add_argument("--task")
    cleanup.add_argument(
        "--older-than", type=int, help="Rolling 24-hour days; omit for configured policy"
    )
    cleanup.add_argument(
        "--status", action="append", choices=["succeeded", "failed", "timeout", "interrupted"]
    )
    cleanup.add_argument(
        "--keep-failures", action="store_true", help="Preserve failed, timeout and interrupted runs"
    )
    mutation_options(cleanup)
    compact = commands.add_parser(
        "compact", help="Reclaim SQLite disk space; requires no running tasks"
    )
    mutation_options(compact)
    history = commands.add_parser(
        "history", help="Paginated run history; lost historical logs are not recoverable"
    )
    history.add_argument("--task")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--offset", type=int, default=0)
    history.add_argument(
        "--timezone",
        default="UTC",
        help="Display UTC, local or an IANA zone; original timestamps unchanged",
    )
    result = commands.add_parser(
        "result", help="Get one run result; process success is not artifact verification"
    )
    result.add_argument("run_id")
    result.add_argument(
        "--timezone",
        default="UTC",
        help="Display UTC, local or an IANA zone; original timestamps unchanged",
    )
    logs = commands.add_parser(
        "logs", help="Paginated UTF-8 logs, invalid bytes replaced; cursor is last seq"
    )
    logs.add_argument("run_id")
    logs.add_argument("--limit", type=int, default=20)
    logs.add_argument("--after", type=int, default=0)
    parser.epilog = 'Task JSON: {"id":"example","argv":["/absolute/executable","arg"],"cwd":"/absolute/directory","schedule":{"kind":"interval","seconds":300},"timeout":3600}. Schedule alternatives: {"kind":"manual"} (no native deployment), {"kind":"daily","time":"09:00"}, {"kind":"weekly","day":"mon","time":"09:00"}. All times are device local; intervals use whole minutes 60..86400 seconds.'


def execute_task(args: argparse.Namespace, service: TaskService) -> dict[str, Any]:
    action = args.action
    if action == "cleanup":
        return service.cleanup(
            args.task,
            args.older_than,
            args.status,
            args.keep_failures,
            args.confirm,
            args.expected_plan,
        )
    if action == "compact":
        return service.compact(args.confirm, args.expected_plan)
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
        return {"runs": repository.history(args.task, args.limit, args.offset, args.timezone)}
    if action == "result":
        return {"run": repository.result(args.run_id, args.timezone)}
    if action == "logs":
        return service.logs(args.run_id, args.limit, args.after)
    raise TickworkError("invalid-command", "Use task --help to discover commands")
