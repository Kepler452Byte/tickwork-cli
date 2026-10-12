"""Standalone stdlib worker, copied before the installed package is replaced."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def save(path: Path, job: dict[str, Any]) -> None:
    descriptor, filename = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(21):
            try:
                os.replace(filename, path)
                break
            except PermissionError as exc:
                # Windows status readers/scanners can briefly deny replacement of an open file.
                if (
                    sys.platform != "win32"
                    or getattr(exc, "winerror", None) not in {5, 32, 33}
                    or attempt == 20
                ):
                    raise
                time.sleep(0.05)
    finally:
        Path(filename).unlink(missing_ok=True)


def wait_for_host(pid: int, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise OSError("Cannot verify host process exit")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError("Host process did not exit")
        finally:
            kernel.CloseHandle(handle)
        return
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    raise TimeoutError("Host process did not exit")


def process_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def invoke(argv: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        stdin=subprocess.DEVNULL,
        creationflags=process_flags(),
    )
    if result.returncode:
        # Child diagnostics stay in the private log, never in the JSON result.
        print("New CLI returned exit code " + str(result.returncode), file=sys.stderr)
        raise RuntimeError("New CLI command failed")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or payload.get("status") not in {"ok", "preview"}:
        raise ValueError("Invalid new CLI result")
    data = payload
    if not isinstance(data, dict):
        raise ValueError("Invalid new CLI payload")
    return data


def run(path: Path, *, wait: bool = True) -> None:
    job = json.loads(path.read_text(encoding="utf-8"))
    try:
        job["state"] = "waiting"
        save(path, job)
        if wait:
            wait_for_host(job["host_pid"])
        job.update(state="running", package_stage="running")
        save(path, job)
        result = subprocess.run(
            job["update_command"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=900,
            creationflags=process_flags(),
            env={**os.environ, **job.get("manager_environment", {})},
        )
        job["manager_exit_code"] = result.returncode
        print("Package manager exit code: " + str(result.returncode))
        if result.returncode:
            raise RuntimeError("Package manager returned a nonzero exit code")
        version = invoke([job["entry_point"], "--version"])
        if version.get("package", job["package"]) != job["package"] or not isinstance(
            version.get("version"), str
        ):
            raise ValueError("Installed package identity could not be verified")
        job.update(
            package_stage="completed",
            installed_version=version["version"],
            resource_stage="running",
        )
        save(path, job)
        cli = [job["entry_point"], "--home", job["home"]]
        preview = invoke([*cli, "upgrade", "--skip-package"])
        if preview.get("package") != job["package"] or preview.get("version") != version["version"]:
            raise ValueError("Package and resource versions differ")
        aligned = invoke(
            [
                *cli,
                "upgrade",
                "--skip-package",
                "--expected-plan",
                preview["expected_plan"],
                "--confirm",
            ]
        )
        if aligned.get("version") != version["version"] or aligned.get("conflicts"):
            raise ValueError("Agent resources were not aligned")
        # Re-read the installed resources to verify completion, including zero-op retries.
        verified = invoke([*cli, "upgrade", "--skip-package"])
        if verified.get("operations") or verified.get("conflicts"):
            raise ValueError("Resource verification did not reach a stable state")
        job.update(
            state="completed",
            resource_stage="completed",
            message="Package verified and registered resources aligned",
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(str(exc), file=sys.stderr)
        if job["package_stage"] != "completed":
            job["package_stage"] = "failed"
            job["resource_stage"] = "skipped"
        else:
            job["resource_stage"] = "failed"
        job.update(
            state="failed", message="Upgrade failed; inspect the operation log and retry explicitly"
        )
    save(path, job)


if __name__ == "__main__":
    run(Path(sys.argv[1]))
