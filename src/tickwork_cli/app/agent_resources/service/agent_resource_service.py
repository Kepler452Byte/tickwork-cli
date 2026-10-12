"""Apply Agent resource ownership, conflict and cleanup policies."""

import json
import re
from pathlib import Path

from tickwork_cli.app.agent_resources.repository.agent_resource_repository import (
    AgentResourceRepository,
)
from tickwork_cli.app.agent_resources.schema.agent_resource_schema import (
    Change,
    OwnedFile,
    Registry,
)
from tickwork_cli.common.hashing import digest
from tickwork_cli.common.operation_error import OperationError


class AgentResourceService:
    def __init__(self, repository: AgentResourceRepository):
        self.repository = repository
        self.distribution = repository.distribution
        self.command = repository.command
        self.state_root = repository.state_root
        self.registry_path = repository.registry_path

    def assets(self) -> dict[str, bytes]:
        return self.repository.assets()

    def hint(self) -> bytes:
        return self.repository.hint()

    def version(self) -> str:
        return self.repository.version()

    def install(
        self,
        skills_dir: Path | None,
        hint_file: Path | None,
        confirm: bool = False,
        expected_plan: str | None = None,
    ) -> dict[str, object]:
        if skills_dir is None and hint_file is None:
            raise OperationError(
                "Provide --skills-dir or --hint-file explicitly", "invalid-input", 2
            )
        return self.sync(confirm, expected_plan, skills_dir, hint_file)

    def list_skills(self) -> dict[str, object]:
        assets = self.assets()
        return {
            "package": self.distribution,
            "version": self.version(),
            "skills": [path.split("/")[0] for path in assets if path.endswith("/SKILL.md")],
        }

    def show(self, name: str, relative: str = "SKILL.md") -> dict[str, object]:
        key = f"{name}/{relative}"
        assets = self.assets()
        if key not in assets:
            raise OperationError("Requested packaged skill resource does not exist", "not-found", 4)
        try:
            text = assets[key].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OperationError(
                "This resource is binary; install it rather than reading it as text",
                "binary-resource",
                2,
            ) from exc
        return {
            "name": name,
            "file": relative,
            "content": text,
            "sha256": digest(assets[key]),
        }

    def check(self) -> dict[str, object]:
        assets = self.assets()
        issues: list[str] = []
        names = {path.split("/")[0] for path in assets}
        for name in sorted(names):
            content = assets.get(f"{name}/SKILL.md", b"").decode("utf-8")
            if not re.search(rf"^name:\s*{re.escape(name)}\s*$", content, re.MULTILINE):
                issues.append(f"{name}: missing or mismatched name")
            if not re.search(r"^description:\s*\S", content, re.MULTILINE):
                issues.append(f"{name}: missing description")
        if issues:
            raise OperationError("; ".join(issues), "invalid-resources", 2)
        return {
            "package": self.distribution,
            "version": self.version(),
            "files": len(assets),
            "skills": len(names),
        }

    def _markers(self) -> tuple[bytes, bytes]:
        return (
            b"<!-- TICKWORK:BEGIN -->",
            b"<!-- TICKWORK:END -->",
        )

    def _block(self, current: bytes) -> tuple[int, int] | None:
        start, end = self._markers()
        counts = current.count(start), current.count(end)
        if counts == (0, 0):
            return None
        if counts != (1, 1) or current.index(start) >= current.index(end):
            raise OperationError(
                "Hint markers are duplicate, incomplete or out of order", "invalid-markers"
            )
        return current.index(start), current.index(end) + len(end)

    def plan(
        self, skills_dir: Path | None = None, hint_file: Path | None = None
    ) -> tuple[list[Change], Registry, list[dict[str, str]], str]:
        self.check()
        raw = self.repository.read(self.registry_path)
        registry = (
            Registry.load(raw, self.distribution)
            if raw is not None
            else Registry(self.distribution, [], [], [])
        )
        # Existing explicit registrations and owned manifests remain authoritative.
        retired: list[Change] = []
        for root in registry.skills:
            manifest = self.repository.resolve(
                Path(root) / "tickwork-task-management/.tickwork-owned.json"
            )
            content = self.repository.read(manifest)
            if content is not None:
                try:
                    entries = json.loads(content)
                    if not isinstance(entries, dict) or not all(
                        isinstance(path, str) for path in entries
                    ):
                        raise ValueError("owned files")
                    known = {item.path for item in registry.files}
                    registry.files.extend(
                        OwnedFile(path, "skill") for path in entries if path not in known
                    )
                except (ValueError, TypeError) as exc:
                    raise OperationError(
                        "Owned resource record is invalid", "invalid-registry"
                    ) from exc
                retired.append(Change(manifest, digest(content), None, "delete"))
        if retired:
            registry.files.extend(
                OwnedFile(path, "hint")
                for path in registry.hints
                if path not in {item.path for item in registry.files}
            )
        # Ownership may only refer to registered, absolute targets.
        for registered_file in registry.files:
            registered_target = self.repository.resolve(Path(registered_file.path))
            valid = (
                str(registered_target) in registry.hints
                if registered_file.kind == "hint"
                else any(
                    registered_target.is_relative_to(self.repository.resolve(Path(root)))
                    for root in registry.skills
                )
            )
            if not valid or str(registered_target) != registered_file.path:
                raise OperationError(
                    "Registry contains a registered_target outside registered locations",
                    "invalid-registry",
                )
        skills = list(registry.skills)
        hints = list(registry.hints)
        for supplied, targets in ((skills_dir, skills), (hint_file, hints)):
            if supplied is not None:
                location = str(self.repository.resolve(supplied))
                if location not in targets:
                    targets.append(location)
        for location in [*skills, *hints]:
            if self.repository.resolve(Path(location)).is_relative_to(self.state_root):
                raise OperationError(
                    "Agent targets must be outside internal CLI state", "unsafe-path"
                )
        old = {item.path: item for item in registry.files}
        desired: dict[str, tuple[bytes, str]] = {}
        for root in skills:
            for relative, asset_content in self.assets().items():
                desired[str(self.repository.resolve(Path(root) / relative))] = (
                    asset_content,
                    "skill",
                )
        start, end = self._markers()
        hint = self.hint()
        if hint:
            for path in hints:
                if path in desired:
                    raise OperationError("Skill and hint destinations overlap", "unsafe-path")
                desired[path] = (start + b"\n" + hint.rstrip(b"\r\n") + b"\n" + end, "hint")
        changes: list[Change] = []
        owned: list[OwnedFile] = []
        conflicts: list[dict[str, str]] = []
        observed: dict[str, str] = {}
        for path in sorted(set(desired) | set(old)):
            target = self.repository.resolve(Path(path))
            current = self.repository.read(target)
            observed[path] = digest(current)
            previous = old.get(path)
            item = desired.get(path)
            kind = item[1] if item else old[path].kind
            block = self._block(current or b"") if kind == "hint" else None
            managed = (
                (current[block[0] : block[1]] if current is not None and block else None)
                if kind == "hint"
                else current
            )
            content = item[0] if item else None
            # Registered resources follow the package; only foreign targets conflict.
            if previous is None and managed is not None and managed != content:
                conflicts.append({"path": path, "code": "unmanaged-target"})
                continue
            if item:
                owned.append(OwnedFile(path, kind))
            updated = content
            if kind == "hint":
                if block:
                    updated = (
                        (current or b"")[: block[0]]
                        + (content or b"")
                        + (current or b"")[block[1] :]
                    )
                elif content:
                    separator = (
                        b""
                        if not current or current.endswith(b"\n\n")
                        else (b"\n" if current.endswith(b"\n") else b"\n\n")
                    )
                    updated = (current or b"") + separator + content + b"\n"
                else:
                    updated = current
            if updated != current:
                changes.append(
                    Change(
                        target,
                        digest(current),
                        updated,
                        "delete"
                        if updated is None
                        else ("update" if current is not None else "create"),
                    )
                )
        new = Registry(
            self.distribution,
            sorted(skills),
            sorted(hints),
            sorted(owned, key=lambda item: item.path),
        )
        encoded = new.encode()
        if raw != encoded and (skills or hints or raw is not None):
            changes.append(Change(self.registry_path, digest(raw), encoded, "register"))
        changes.extend(retired)
        plan_data = {
            "package": self.distribution,
            "version": self.version(),
            "registry_hash": digest(raw),
            "observed": observed,
            "operations": [item.describe() for item in changes],
            "conflicts": conflicts,
        }
        plan_hash = digest(json.dumps(plan_data, sort_keys=True).encode())
        return changes, new, conflicts, plan_hash

    def sync(
        self,
        confirm: bool = False,
        expected_plan: str | None = None,
        skills_dir: Path | None = None,
        hint_file: Path | None = None,
    ) -> dict[str, object]:
        changes, _registry, conflicts, plan_hash = self.plan(skills_dir, hint_file)
        result: dict[str, object] = {
            "package": self.distribution,
            "version": self.version(),
            "expected_plan": plan_hash,
            "plan": plan_hash,
            "operations": [item.describe() for item in changes],
            "conflicts": conflicts,
            "write_performed": False,
        }
        if confirm:
            if expected_plan != plan_hash:
                raise OperationError(
                    "Preview changed or --expected-plan is missing; preview again", "plan-conflict"
                )
            if conflicts:
                raise OperationError(
                    "Unregistered targets conflict with resource alignment; no files were written",
                    "resource-conflict",
                )
            if changes:
                with self.repository.lock([change.path for change in changes]):
                    _new_changes, _new_registry, _new_conflicts, fresh_hash = self.plan(
                        skills_dir, hint_file
                    )
                    if fresh_hash != plan_hash:
                        raise OperationError("Resources changed since preview", "plan-conflict")
                    for change in changes:
                        if digest(self.repository.read(change.path)) != change.before:
                            raise OperationError(
                                "Target changed during synchronization", "plan-conflict"
                            )
                        if change.content is None:
                            self.repository.remove(change.path)
                        else:
                            self.repository.write(change.path, change.content)
                result["write_performed"] = True
        return result
