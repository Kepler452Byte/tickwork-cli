import sys
from pathlib import Path

from tickwork_cli.app.task.adapter.launchd_scheduler import LaunchdScheduler
from tickwork_cli.app.task.adapter.scheduler_protocol import Scheduler
from tickwork_cli.app.task.adapter.systemd_scheduler import SystemdScheduler
from tickwork_cli.app.task.adapter.windows_scheduler import WindowsScheduler
from tickwork_cli.app.task.service.task_service import TaskService
from tickwork_cli.common.application_errors import TickworkError


def task_service(home: Path) -> TaskService:
    scheduler: Scheduler
    if sys.platform == "linux":
        scheduler = SystemdScheduler(home)
    elif sys.platform == "darwin":
        scheduler = LaunchdScheduler(home)
    elif sys.platform == "win32":
        scheduler = WindowsScheduler(home)
    else:
        raise TickworkError("unsupported-platform", sys.platform)
    return TaskService(home, scheduler)
