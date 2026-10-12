"""Read packaged assets and persist explicitly addressed files."""

from contextlib import AbstractContextManager
from importlib import metadata, resources
from pathlib import Path

from tickwork_cli.common.filesystem import atomic_write, read_bytes, safe_path, write_lock


class AgentResourceRepository:
    def __init__(
        self, distribution: str, command: str, state_root: Path, package: str = "tickwork_cli"
    ):
        self.distribution = distribution
        self.command = command
        self.state_root = state_root.expanduser().absolute()
        self.package = package
        self.registry_path = self.state_root / "local.yaml"

    def assets(self) -> dict[str, bytes]:
        root = resources.files(self.package).joinpath("resources", "skills")
        assets: dict[str, bytes] = {}

        def visit(node: resources.abc.Traversable, prefix: str) -> None:
            for child in sorted(node.iterdir(), key=lambda item: item.name):
                relative = prefix + child.name
                if child.is_dir():
                    visit(child, relative + "/")
                else:
                    assets[relative] = child.read_bytes()

        if root.is_dir():
            visit(root, "")
        return assets

    def version(self) -> str:
        return metadata.version(self.distribution)

    def hint(self) -> bytes:
        path = resources.files(self.package).joinpath("resources", "agent_hint.md")
        return path.read_bytes() if path.is_file() else b""

    def resolve(self, path: Path) -> Path:
        return safe_path(path)

    def read(self, path: Path) -> bytes | None:
        return read_bytes(path)

    def write(self, path: Path, content: bytes) -> None:
        atomic_write(path, content)

    def remove(self, path: Path) -> None:
        safe_path(path).unlink(missing_ok=True)

    def lock(self, targets: list[Path]) -> AbstractContextManager[None]:
        return write_lock(self.state_root, targets)
