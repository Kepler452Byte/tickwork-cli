import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from tickwork_cli.app.task.adapter.scheduler_protocol import marker, namespace, runner_argv
from tickwork_cli.app.task.schema.task_schema import DAYS, Task
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.process import command

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)


def element(
    parent: ET.Element, name: str, text: str | None = None, **attributes: str
) -> ET.Element:
    child = ET.SubElement(parent, f"{{{NS}}}{name}", attributes)
    child.text = text
    return child


class WindowsScheduler:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.prefix = namespace(home)

    def name(self, task_id: str) -> str:
        return f"{self.prefix}-{task_id}"

    def query(self, task_id: str) -> dict[str, Any] | None:
        # COM avoids parsing localized schtasks CSV or conflating absence with access denied.
        name = self.name(task_id)
        script = f"""$ErrorActionPreference='Stop';
$s=New-Object -ComObject Schedule.Service; $s.Connect();
try {{ $t=$s.GetFolder('\\').GetTask('{name}');
@{{xml=$t.Xml;enabled=$t.Enabled;state=$t.State;last_result=$t.LastTaskResult}} | ConvertTo-Json -Compress
}} catch {{ if ($_.Exception.HResult -eq -2147024894) {{ 'null' }} else {{ throw }} }}"""
        output = command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        data: dict[str, Any] | None = json.loads(output)
        if data is not None:
            root = ET.fromstring(data["xml"])
            if root.findtext(f"{{{NS}}}RegistrationInfo/{{{NS}}}Description") != marker(
                self.home, task_id
            ):
                raise TickworkError("foreign-task", f"Refusing to modify unowned task {name}")
        return data

    def state(self, task_id: str) -> dict[str, Any]:
        data = self.query(task_id)
        return {
            "deployed": data is not None,
            "enabled": bool(data and data["enabled"]),
            "active": bool(data and data["state"] == 4),
            "last_result": data["last_result"] if data else None,
        }

    def xml(self, task: Task, enabled: bool, sid: str) -> bytes:
        root = ET.Element(f"{{{NS}}}Task", {"version": "1.2"})
        registration = element(root, "RegistrationInfo")
        element(registration, "Description", marker(self.home, task.id))
        triggers = element(root, "Triggers")
        schedule = task.schedule
        trigger = element(
            triggers, "TimeTrigger" if schedule["kind"] == "interval" else "CalendarTrigger"
        )
        if schedule["kind"] == "interval":
            repetition = element(trigger, "Repetition")
            element(repetition, "Interval", f"PT{schedule['seconds'] // 60}M")
            element(repetition, "StopAtDurationEnd", "false")
            # An immediate first trigger is avoided; subsequent ticks belong to Task Scheduler.
            from datetime import timedelta

            boundary = datetime.now() + timedelta(seconds=schedule["seconds"])
            element(trigger, "StartBoundary", boundary.isoformat(timespec="seconds"))
        else:
            element(trigger, "StartBoundary", f"2020-01-01T{schedule['time']}:00")
        element(trigger, "Enabled", "true")
        if schedule["kind"] == "daily":
            element(element(trigger, "ScheduleByDay"), "DaysInterval", "1")
        elif schedule["kind"] == "weekly":
            week = element(trigger, "ScheduleByWeek")
            element(week, "WeeksInterval", "1")
            day = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[
                DAYS.index(schedule["day"])
            ]
            element(element(week, "DaysOfWeek"), day)
        principal = element(element(root, "Principals"), "Principal", id="Author")
        element(principal, "UserId", sid)
        element(principal, "LogonType", "InteractiveToken")
        element(principal, "RunLevel", "LeastPrivilege")
        settings = element(root, "Settings")
        for key, value in {
            "MultipleInstancesPolicy": "IgnoreNew",
            "DisallowStartIfOnBatteries": "false",
            "StopIfGoingOnBatteries": "false",
            "StartWhenAvailable": "false",
            "RunOnlyIfNetworkAvailable": "false",
            "AllowStartOnDemand": "true",
            "Enabled": str(enabled).lower(),
            "ExecutionTimeLimit": f"PT{task.timeout + 60}S",
        }.items():
            element(settings, key, value)
        actions = element(root, "Actions", Context="Author")
        action = element(actions, "Exec")
        argv = runner_argv(self.home, task.id)
        element(action, "Command", argv[0])
        element(action, "Arguments", subprocess.list2cmdline(argv[1:]))
        element(action, "WorkingDirectory", str(self.home))
        return cast(bytes, ET.tostring(root, encoding="utf-16", xml_declaration=True))

    def deploy(self, task: Task, enabled: bool) -> None:
        self.query(task.id)
        sid = command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
            ]
        ).strip()
        with tempfile.TemporaryDirectory(prefix="tickwork-") as temporary:
            path = Path(temporary) / "task.xml"
            path.write_bytes(self.xml(task, enabled, sid))
            command(["schtasks.exe", "/Create", "/TN", self.name(task.id), "/XML", str(path), "/F"])

    def remove(self, task_id: str) -> None:
        if self.query(task_id) is not None:
            command(["schtasks.exe", "/Delete", "/TN", self.name(task_id), "/F"])

    def doctor(self) -> dict[str, Any]:
        command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$s=New-Object -ComObject Schedule.Service; $s.Connect(); $s.Connected",
            ]
        )
        return {
            "platform": "windows",
            "scheduler": "task-scheduler",
            "available": True,
            "session_requirement": "Current user must be logged in (InteractiveToken, LeastPrivilege).",
            "native_logs": "Task Scheduler LastTaskResult and Microsoft-Windows-TaskScheduler/Operational",
        }
