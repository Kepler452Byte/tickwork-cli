import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tickwork_cli.app.task.adapter.scheduler_protocol import marker, namespace, runner_argv
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.process import command


def quote(value: str) -> str:
    return (
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
        .replace("\n", "\\n")
        + '"'
    )


class SystemdScheduler:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.prefix = namespace(home)
        self.directory = (
            Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
        )

    def name(self, task_id: str) -> str:
        return f"{self.prefix}-{task_id}"

    def paths(self, task_id: str) -> tuple[Path, Path]:
        return (
            self.directory / f"{self.name(task_id)}.service",
            self.directory / f"{self.name(task_id)}.timer",
        )

    def owned(self, task_id: str) -> None:
        expected = "# " + marker(self.home, task_id)
        for path in self.paths(task_id):
            if path.exists() and not path.read_text(encoding="utf-8").startswith(expected + "\n"):
                raise TickworkError("foreign-task", f"Refusing to modify unowned unit {path}")

    def state(self, task_id: str) -> dict[str, Any]:
        self.owned(task_id)
        name = self.name(task_id) + ".timer"
        output = command(
            [
                "systemctl",
                "--user",
                "show",
                name,
                "--property=FragmentPath,LoadState,ActiveState,UnitFileState,NextElapseUSecRealtime,NextElapseUSecMonotonic",
            ]
        )
        properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        fragment = properties.get("FragmentPath")
        if fragment and not Path(fragment).read_text(encoding="utf-8").startswith(
            "# " + marker(self.home, task_id) + "\n"
        ):
            raise TickworkError(
                "foreign-task", "Loaded timer does not have matching Tickwork ownership"
            )
        exists = properties.get("LoadState") != "not-found"
        active = properties.get("ActiveState") == "active"
        enabled = properties.get("UnitFileState") == "enabled"
        return {
            "deployed": exists,
            "enabled": active or enabled,
            "active": active,
            "persistent": enabled,
            "details": properties,
        }

    def deploy(self, task: Task, enabled: bool) -> None:
        self.owned(task.id)
        service, timer = self.paths(task.id)
        self.directory.mkdir(parents=True, exist_ok=True)
        header = "# " + marker(self.home, task.id) + "\n"
        service.write_text(
            header
            + "[Unit]\nDescription=Tickwork managed command\n[Service]\nType=oneshot\nExecStart="
            + " ".join(quote(arg) for arg in runner_argv(self.home, task.id))
            + f"\nTimeoutStartSec={task.timeout + 60}\nKillMode=control-group\n",
            encoding="utf-8",
        )
        schedule = task.schedule
        if schedule["kind"] == "interval":
            rule = f"OnActiveSec={schedule['seconds']}s\nOnUnitActiveSec={schedule['seconds']}s"
        else:
            day = "" if schedule["kind"] == "daily" else str(schedule["day"]).title() + " "
            rule = f"OnCalendar={day}*-*-* {schedule['time']}:00"
        timer.write_text(
            header
            + f"[Unit]\nDescription=Tickwork managed timer\n[Timer]\n{rule}\nAccuracySec=1s\nPersistent=false\nUnit={service.name}\n[Install]\nWantedBy=timers.target\n",
            encoding="utf-8",
        )
        command(["systemctl", "--user", "daemon-reload"])
        command(["systemctl", "--user", "enable" if enabled else "disable", timer.name])
        command(["systemctl", "--user", "restart" if enabled else "stop", timer.name])

    def remove(self, task_id: str) -> None:
        self.owned(task_id)
        _, timer = self.paths(task_id)
        state = self.state(task_id)
        if state["deployed"]:
            command(["systemctl", "--user", "disable", "--now", timer.name])
        for path in self.paths(task_id):
            path.unlink(missing_ok=True)
        command(["systemctl", "--user", "daemon-reload"])
        # The service is not stopped: deleting a definition never kills an active run.

    def doctor(self) -> dict[str, Any]:
        if sys.platform == "win32":
            raise TickworkError("unsupported-platform", "systemd requires Linux")
        command(["systemctl", "--user", "show-environment"])
        result = subprocess.run(
            ["loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value"],
            capture_output=True,
            text=True,
        )
        return {
            "platform": "linux",
            "scheduler": "systemd-user",
            "available": True,
            "linger": result.stdout.strip() or "unknown",
            "session_requirement": "User manager must be running; Tickwork does not enable lingering.",
            "native_logs": "journalctl --user -u <unit>.service",
        }
