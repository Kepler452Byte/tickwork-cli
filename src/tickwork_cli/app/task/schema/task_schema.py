import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tickwork_cli.common.application_errors import TickworkError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Task:
    id: str
    argv: list[str]
    cwd: str
    schedule: dict[str, Any]
    timeout: int = 3600

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", self.id):
            raise TickworkError("invalid-task", "id must match [a-z][a-z0-9-]{0,47}")
        if (
            not isinstance(self.argv, list)
            or not self.argv
            or any(not isinstance(arg, str) or "\0" in arg or "\n" in arg for arg in self.argv)
        ):
            raise TickworkError(
                "invalid-task", "argv must be a nonempty string array without NUL/newline"
            )
        if not Path(self.argv[0]).is_absolute() or not Path(self.argv[0]).is_file():
            raise TickworkError(
                "invalid-task", "argv[0] must be an absolute existing executable path"
            )
        if (
            not isinstance(self.cwd, str)
            or not Path(self.cwd).is_absolute()
            or not Path(self.cwd).is_dir()
        ):
            raise TickworkError("invalid-task", "cwd must be an absolute existing directory")
        if type(self.timeout) is not int or not 1 <= self.timeout <= 86400:
            raise TickworkError("invalid-task", "timeout must be 1..86400 seconds")
        schedule = self.schedule
        if not isinstance(schedule, dict):
            raise TickworkError("invalid-task", "schedule must be an object")
        kind = schedule.get("kind")
        if kind == "interval":
            seconds = schedule.get("seconds")
            valid = (
                set(schedule) == {"kind", "seconds"}
                and type(seconds) is int
                and 60 <= seconds <= 86400
                and seconds % 60 == 0
            )
        elif kind in {"daily", "weekly"}:
            time = schedule.get("time")
            valid = (
                isinstance(time, str)
                and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time) is not None
            )
            keys = {"kind", "time"}
            if kind == "weekly":
                keys.add("day")
                valid = valid and schedule.get("day") in DAYS
            valid = valid and set(schedule) == keys
        else:
            valid = False
        if not valid:
            raise TickworkError(
                "invalid-task",
                "schedule: interval seconds (whole minutes 60..86400), daily HH:MM, or weekly day mon..sun HH:MM",
            )

    def data(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def parse(cls, data: object) -> "Task":
        if not isinstance(data, dict) or set(data) - {"id", "argv", "cwd", "schedule", "timeout"}:
            raise TickworkError(
                "invalid-task", "task must contain only id, argv, cwd, schedule, timeout"
            )
        try:
            return cls(**data)
        except TypeError as exc:
            raise TickworkError("invalid-task", str(exc)) from exc
