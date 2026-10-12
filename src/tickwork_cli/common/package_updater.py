"""Installation-channel adapter and durable detached upgrade jobs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import uuid
from importlib import metadata
from pathlib import Path

from tickwork_cli.common.filesystem import (
    atomic_write,
    read_bytes,
    write_lock,
)
from tickwork_cli.common.operation_error import OperationError
from tickwork_cli.common.process import no_window_flags


class PackageUpdater:
    def __init__(self, distribution: str, command: str, state_root: Path):
        self.distribution = distribution
        self.command = command
        self.state_root = state_root.expanduser().absolute()

    def plan(self) -> dict[str, object]:
        distribution = metadata.distribution(self.distribution)
        direct = distribution.read_text("direct_url.json")
        try:
            editable = bool(json.loads(direct or "{}").get("dir_info", {}).get("editable"))
        except (ValueError, AttributeError):
            editable = False
        manager = "editable" if editable else "unknown"
        prefix = Path(sys.prefix)
        if not editable:
            try:
                receipt = prefix / "uv-receipt.toml"
                pipx_metadata = prefix / "pipx_metadata.json"
                if receipt.is_file():
                    data = tomllib.loads(receipt.read_text(encoding="utf-8"))
                    requirements = data.get("tool", {}).get("requirements", [])
                    if any(
                        item.get("name", "").replace("_", "-")
                        == self.distribution.replace("_", "-")
                        for item in requirements
                    ):
                        manager = "uv-tool"
                elif pipx_metadata.is_file():
                    data = json.loads(pipx_metadata.read_text(encoding="utf-8"))
                    main = data.get("main_package", {})
                    if main.get("package", "").replace("_", "-") == self.distribution.replace(
                        "_", "-"
                    ):
                        manager = "pipx"
            except (ValueError, TypeError, AttributeError):
                manager = "unknown"
        executable = (
            shutil.which("uv" if manager == "uv-tool" else "pipx")
            if manager in {"uv-tool", "pipx"}
            else None
        )
        command_path = (
            Path(sys.prefix)
            / ("Scripts" if os.name == "nt" else "bin")
            / (self.command + (".exe" if os.name == "nt" else ""))
        )
        argv = (
            (
                [executable, "tool", "upgrade", self.distribution]
                if manager == "uv-tool"
                else [executable, "upgrade", prefix.name]
            )
            if executable
            else []
        )
        supported = bool(argv and command_path.is_file())
        hint = (
            None
            if supported
            else (
                "Editable install: update the source and reinstall, then align resources with --skip-package"
                if editable
                else "Use the original installation channel to update; no global pip command will be guessed"
            )
        )
        return {
            "package": self.distribution,
            "current_version": distribution.version,
            "target": "latest-available-from-installation-channel",
            "manager": manager,
            "supported": supported,
            "update_command": argv,
            "entry_point": str(command_path),
            "hint": hint,
            "manager_environment": {"UV_TOOL_DIR": str(prefix.parent)}
            if manager == "uv-tool"
            else ({"PIPX_HOME": str(prefix.parent.parent)} if manager == "pipx" else {}),
        }

    def start(self, plan: dict[str, object], expected_plan: str) -> dict[str, object]:
        operation_id = uuid.uuid4().hex
        folder = self.state_root / "upgrades" / operation_id
        job_path = folder / "result.json"
        log_path = folder / "updater.log"
        source = Path(__file__).with_name("package_update_worker.py")
        with write_lock(self.state_root):
            active_path = self.state_root / "active-upgrade.json"
            active = read_bytes(active_path)
            if active:
                try:
                    previous = json.loads(active)["operation_id"]
                    state = self.status(previous)
                except (ValueError, KeyError, TypeError) as exc:
                    raise OperationError("Active upgrade record is invalid", "invalid-job") from exc
                if state.get("state") not in {"completed", "failed"}:
                    raise OperationError(
                        "An upgrade is already active; query its result before retrying",
                        "upgrade-active",
                    )
            # Copy a stdlib-only worker outside the environment being replaced.
            atomic_write(folder / "runner.py", source.read_bytes())
            job = {
                "operation_id": operation_id,
                "state": "scheduled",
                "package_stage": "pending",
                "resource_stage": "pending",
                "package": self.distribution,
                "command": self.command,
                "current_version": plan["current_version"],
                "update_command": plan["update_command"],
                "entry_point": plan["entry_point"],
                "host_pid": os.getpid(),
                "manager_environment": plan.get("manager_environment", {}),
                "log_path": str(log_path),
                "expected_plan": expected_plan,
                "home": str(self.state_root),
            }
            atomic_write(job_path, json.dumps(job, sort_keys=True).encode())
            atomic_write(active_path, json.dumps({"operation_id": operation_id}).encode())
            # The base interpreter is outside the tool venv and remains usable on Windows.
            base_python = getattr(sys, "_base_executable", sys.executable)
            try:
                with log_path.open("ab") as log:
                    # Separate branches keep subprocess typing precise across platforms.
                    if sys.platform == "win32":
                        subprocess.Popen(
                            [base_python, str(folder / "runner.py"), str(job_path)],
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=log,
                            creationflags=no_window_flags() | subprocess.CREATE_NEW_PROCESS_GROUP,
                            close_fds=True,
                        )
                    else:
                        subprocess.Popen(
                            [base_python, str(folder / "runner.py"), str(job_path)],
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=log,
                            start_new_session=True,
                            close_fds=True,
                        )
            except OSError as exc:
                job.update(
                    state="failed", package_stage="failed", message="Unable to start updater"
                )
                atomic_write(job_path, json.dumps(job).encode())
                raise OperationError(
                    "Unable to start detached updater; see operation result", "upgrade-failed", 6
                ) from exc
        return {
            "operation_id": operation_id,
            "state": "scheduled",
            "package_stage": "pending",
            "resource_stage": "pending",
            "log_path": str(log_path),
        }

    def status(self, operation_id: str) -> dict[str, object]:
        if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
            raise OperationError("Invalid upgrade operation ID", "invalid-input", 2)
        path = self.state_root / "upgrades" / operation_id / "result.json"
        raw = read_bytes(path)
        if raw is None:
            raise OperationError("Upgrade operation does not exist", "not-found", 4)
        try:
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or payload.get("package") != self.distribution
                or payload.get("operation_id") != operation_id
            ):
                raise ValueError("identity")
        except (ValueError, TypeError) as exc:
            raise OperationError("Upgrade result is invalid", "invalid-job") from exc
        result: dict[str, object] = payload
        # Expose results, not executable commands or process internals.
        return {
            key: value
            for key, value in result.items()
            if key not in {"update_command", "host_pid", "entry_point"}
        }
