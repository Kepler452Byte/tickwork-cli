import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from tickwork_cli.app.task.adapter.scheduler_protocol import marker, namespace, runner_argv
from tickwork_cli.app.task.schema.task_schema import DAYS, Task
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.process import command


class LaunchdScheduler:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.prefix = namespace(home)
        self.directory = Path.home() / "Library/LaunchAgents"
        if sys.platform == "win32":
            raise TickworkError("unsupported-platform", "launchd requires macOS")
        self.domain = f"gui/{os.getuid()}"

    def label(self, task_id: str) -> str:
        return f"io.tickwork.{self.prefix}.{task_id}"

    def path(self, task_id: str) -> Path:
        return self.directory / (self.label(task_id) + ".plist")

    def owned(self, task_id: str) -> dict[str, Any] | None:
        path = self.path(task_id)
        if not path.exists():
            return None
        with path.open("rb") as handle:
            data: dict[str, Any] = plistlib.load(handle)
        if data.get("TickworkOwner") != marker(self.home, task_id):
            raise TickworkError("foreign-task", f"Refusing to modify unowned plist {path}")
        return data

    def loaded(self, task_id: str) -> bool:
        result = subprocess.run(
            ["launchctl", "print", f"{self.domain}/{self.label(task_id)}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 113:
            return False
        raise TickworkError("scheduler-failed", result.stderr.strip())

    def state(self, task_id: str) -> dict[str, Any]:
        owned = self.owned(task_id)
        loaded = self.loaded(task_id)
        if loaded and owned is None:
            raise TickworkError("foreign-task", "Loaded launchd job has no owned plist")
        # Bootstrapped jobs in the GUI domain are authoritative, not a YAML enabled flag.
        return {
            "deployed": self.path(task_id).exists() or loaded,
            "enabled": loaded,
            "active": loaded,
        }

    def deploy(self, task: Task, enabled: bool) -> None:
        self.state(task.id)
        if self.loaded(task.id):
            command(["launchctl", "bootout", f"{self.domain}/{self.label(task.id)}"])
        data: dict[str, Any] = {
            "Label": self.label(task.id),
            "TickworkOwner": marker(self.home, task.id),
            "ProgramArguments": runner_argv(self.home, task.id),
            "ProcessType": "Background",
            "RunAtLoad": False,
            "Disabled": not enabled,
        }
        schedule = task.schedule
        if schedule["kind"] == "interval":
            data["StartInterval"] = schedule["seconds"]
        else:
            hour, minute = map(int, schedule["time"].split(":"))
            calendar = {"Hour": hour, "Minute": minute}
            if schedule["kind"] == "weekly":
                calendar["Weekday"] = (DAYS.index(schedule["day"]) + 1) % 7
            data["StartCalendarInterval"] = calendar
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.path(task.id).open("wb") as handle:
            plistlib.dump(data, handle)
        target = f"{self.domain}/{self.label(task.id)}"
        command(["launchctl", "enable" if enabled else "disable", target])
        if enabled:
            command(["launchctl", "bootstrap", self.domain, str(self.path(task.id))])

    def remove(self, task_id: str) -> None:
        self.state(task_id)
        if self.loaded(task_id):
            command(["launchctl", "bootout", f"{self.domain}/{self.label(task_id)}"])
        command(["launchctl", "enable", f"{self.domain}/{self.label(task_id)}"])
        self.path(task_id).unlink(missing_ok=True)

    def doctor(self) -> dict[str, Any]:
        command(["launchctl", "print", self.domain])
        return {
            "platform": "macos",
            "scheduler": "launchd-user",
            "available": True,
            "session_requirement": "Logged-in GUI user session required.",
            "native_logs": "launchctl print gui/<uid>/<label>; log show --predicate 'process == \"launchd\"'",
            "sleep_behavior": "launchd may coalesce missed calendar triggers once on wake; Tickwork adds no catch-up.",
        }
