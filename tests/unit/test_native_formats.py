import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from tickwork_cli.app.task.adapter.scheduler_protocol import namespace, runner_argv
from tickwork_cli.app.task.adapter.systemd_scheduler import quote
from tickwork_cli.app.task.adapter.windows_scheduler import NS, WindowsScheduler
from tickwork_cli.app.task.schema.task_schema import Task


def test_windows_xml_preserves_paths_schedule_and_security(task: Task, tmp_path: Path) -> None:
    home = tmp_path / "spaces & unicode中文"
    scheduler = WindowsScheduler(home)
    for schedule in (
        {"kind": "interval", "seconds": 300},
        {"kind": "daily", "time": "09:00"},
        {"kind": "weekly", "day": "sun", "time": "12:00"},
    ):
        definition = Task(task.id, task.argv, task.cwd, schedule)
        root = ET.fromstring(scheduler.xml(definition, False, "S-1-5-21-test"))
        assert (
            root.findtext(f"{{{NS}}}Principals/{{{NS}}}Principal/{{{NS}}}LogonType")
            == "InteractiveToken"
        )
        assert root.findtext(f"{{{NS}}}Settings/{{{NS}}}Enabled") == "false"
        assert root.findtext(
            f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments"
        ) == subprocess.list2cmdline(runner_argv(home, task.id)[1:])


def test_systemd_escaping_and_namespace(tmp_path: Path) -> None:
    assert quote('a%$"\\b') == '"a%%$$\\"\\\\b"'
    assert namespace(tmp_path) != namespace(tmp_path / "other")
