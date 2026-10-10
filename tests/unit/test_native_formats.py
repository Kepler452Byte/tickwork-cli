import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tickwork_cli.app.task.adapter.scheduler_protocol import namespace, runner_argv
from tickwork_cli.app.task.adapter.systemd_scheduler import quote
from tickwork_cli.app.task.adapter.windows_scheduler import NS, WindowsScheduler
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.common.application_errors import TickworkError


def test_windows_xml_preserves_paths_schedule_and_security(
    task: Task, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "Python 中文 space" / "python.exe"
    python.parent.mkdir()
    pythonw = python.with_name("pythonw.exe")
    pythonw.touch()
    monkeypatch.setattr(
        "tickwork_cli.app.task.adapter.windows_scheduler.sys.executable", str(python)
    )
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
        assert root.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Command") == str(pythonw)
        assert root.findtext(
            f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments"
        ) == subprocess.list2cmdline(runner_argv(home, task.id)[1:])


def test_systemd_escaping_and_namespace(tmp_path: Path) -> None:
    assert quote('a%$"\\b') == '"a%%$$\\"\\\\b"'
    assert namespace(tmp_path) != namespace(tmp_path / "other")


def test_windows_deployment_requires_same_environment_pythonw(
    task: Task, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tickwork_cli.app.task.adapter.windows_scheduler.sys.executable",
        str(tmp_path / "missing" / "python.exe"),
    )
    with pytest.raises(TickworkError) as error:
        WindowsScheduler(tmp_path).xml(task, False, "S-1-test")
    assert error.value.code == "windowless-python-unavailable"
