import subprocess
from pathlib import Path

from tickwork_cli.common.application_errors import TickworkError


def command(argv: list[str], *, allowed_codes: tuple[int, ...] = (0,)) -> str:
    powershell = Path(argv[0]).name.lower() == "powershell.exe"
    if powershell:
        argv = [
            *argv[:-1],
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + argv[-1],
        ]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8" if powershell else None,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TickworkError("scheduler-unavailable", str(exc)) from exc
    if result.returncode not in allowed_codes:
        raise TickworkError(
            "scheduler-failed", f"{argv[0]} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout
