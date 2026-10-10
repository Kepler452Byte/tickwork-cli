import sys
from functools import cached_property

from tickwork_cli.application_settings import ApplicationSettings
from tickwork_cli.common.database.database_session import DatabaseSession
from tickwork_cli.app.task.adapter.scheduler_protocol import Scheduler
from tickwork_cli.app.task.adapter.launchd_scheduler import LaunchdScheduler
from tickwork_cli.app.task.adapter.systemd_scheduler import SystemdScheduler
from tickwork_cli.app.task.adapter.windows_scheduler import WindowsScheduler
from tickwork_cli.app.task.repository.task_repository import TaskRepository
from tickwork_cli.app.task.repository.task_run_repository import RUN_SCHEMA, TaskRunRepository
from tickwork_cli.app.task.service.task_service import TaskService
from tickwork_cli.common.application_errors import TickworkError


class ApplicationContainer:
    """Own application resources and connect concrete collaborators."""

    def __init__(self, settings: ApplicationSettings):
        self.settings = settings
        self.database = DatabaseSession(settings.database_path)

    def initialize(self) -> None:
        self.database.initialize(RUN_SCHEMA)

    @cached_property
    def scheduler(self) -> Scheduler:
        home = self.settings.home
        if sys.platform == "linux":
            return SystemdScheduler(home)
        if sys.platform == "darwin":
            return LaunchdScheduler(home)
        if sys.platform == "win32":
            return WindowsScheduler(home)
        raise TickworkError("unsupported-platform", sys.platform)

    @cached_property
    def task_service(self) -> TaskService:
        return TaskService(
            self.settings.home,
            self.scheduler,
            TaskRepository(self.settings.home),
            TaskRunRepository(self.database),
        )

    def close(self) -> None:
        self.database.close()
