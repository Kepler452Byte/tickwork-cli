"""Resource ownership records and explicit synchronization plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from tickwork_cli.common.hashing import digest
from tickwork_cli.common.operation_error import OperationError


@dataclass(frozen=True)
class OwnedFile:
    path: str
    kind: str


@dataclass
class Registry:
    distribution: str
    skills: list[str]
    hints: list[str]
    files: list[OwnedFile]

    @classmethod
    def load(cls, raw: bytes, distribution: str) -> Registry:
        try:
            data = yaml.safe_load(raw)
            if not isinstance(data, dict) or data.get("distribution", distribution) != distribution:
                raise ValueError("identity")
            targets = data["agent_resources"]
            if not isinstance(targets, list):
                raise ValueError("targets")
            skills: list[str] = []
            hints: list[str] = []
            for target in targets:
                if (
                    not isinstance(target, dict)
                    or set(target) - {"skills_dir", "agents_file"}
                    or not target
                ):
                    raise ValueError("target")
                for field, locations in (("skills_dir", skills), ("agents_file", hints)):
                    if field in target:
                        location = target[field]
                        if not isinstance(location, str) or not Path(location).is_absolute():
                            raise ValueError("absolute target")
                        if location not in locations:
                            locations.append(location)
            files = data.get("agent_resource_files", [])
            if not isinstance(files, list):
                raise ValueError("files")
            owned: list[OwnedFile] = []
            for item in files:
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(key), str) for key in ("path", "kind")
                ):
                    raise ValueError("files")
                if item["kind"] not in {"skill", "hint"}:
                    raise ValueError("kind")
                owned.append(OwnedFile(item["path"], item["kind"]))
            if len({item.path for item in owned}) != len(owned):
                raise ValueError("duplicate paths")
            return cls(distribution, skills, hints, owned)
        except (ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
            raise OperationError(
                "Resource registry is invalid; preserve it and repair explicitly",
                "invalid-registry",
            ) from exc

    def encode(self) -> bytes:
        targets = [{"skills_dir": path} for path in self.skills]
        targets += [{"agents_file": path} for path in self.hints]
        return yaml.safe_dump(
            {
                "distribution": self.distribution,
                "agent_resources": targets,
                "agent_resource_files": [asdict(item) for item in self.files],
            },
            allow_unicode=True,
            sort_keys=True,
        ).encode()


@dataclass(frozen=True)
class Change:
    path: Path
    before: str
    content: bytes | None
    action: str

    def describe(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "action": self.action,
            "expected_hash": self.before,
            "new_hash": digest(self.content),
        }
