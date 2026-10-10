import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.request
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version


def latest_version() -> str | None:
    try:
        with urllib.request.urlopen(
            "https://pypi.org/pypi/tickwork-cli/json", timeout=3
        ) as response:
            value = json.load(response)["info"]["version"]
        return value if isinstance(value, str) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def newer(candidate: str | None, current: str) -> bool:
    try:
        return candidate is not None and Version(candidate) > Version(current)
    except InvalidVersion:
        return False


def update_command() -> tuple[str, list[str] | None]:
    direct_url = distribution("tickwork-cli").read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
        return "editable", None
    parts = [part.casefold() for part in Path(sys.prefix).parts]
    if "uv" in parts and "tools" in parts:
        return "uv-tool", [
            "uv",
            "tool",
            "upgrade",
            "tickwork-cli",
            "--default-index",
            "https://pypi.org/simple",
        ]
    if "pipx" in parts and "venvs" in parts:
        return "pipx", [
            "pipx",
            "upgrade",
            "tickwork-cli",
            "--pip-args=--index-url https://pypi.org/simple",
        ]
    return "unknown", None


def updater_script(update: list[str], align: list[str], pid: int, windows: bool) -> str:
    if windows:

        def command(argv: list[str]) -> str:
            return "& " + " ".join("'" + value.replace("'", "''") + "'" for value in argv)

        return f"$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $parent = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($null -ne $parent) {{ $parent.WaitForExit() }}; {command(update)}; if ($LASTEXITCODE -eq 0) {{ {command(align)} }}; exit $LASTEXITCODE"
    return f"while kill -0 {pid} 2>/dev/null; do sleep 0.2; done; {shlex.join(update)} && {shlex.join(align)}"


def spawn_update(update: list[str], home: Path) -> Path:
    executable = shutil.which("tickwork")
    if executable is None:
        raise OSError("Installed tickwork executable was not found in PATH")
    align = [executable, "--home", str(home), "upgrade", "--skip-package"]
    script = updater_script(update, align, os.getpid(), os.name == "nt")
    argv = (
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        if os.name == "nt"
        else ["/bin/sh", "-c", script]
    )
    home.mkdir(parents=True, exist_ok=True)
    log = home / "upgrade.log"
    options: dict[str, Any] = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    with log.open("w", encoding="utf-8") as output:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=output, **options)
    return log
