import argparse
import os
import re
import subprocess
import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag", default=os.getenv("RELEASE_TAG"), required=not os.getenv("RELEASE_TAG")
    )
    tag = parser.parse_args().tag
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit("Release tag must be v<major>.<minor>.<patch>")
    package_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if tag != f"v{package_version}" or version("tickwork-cli") != package_version:
        raise SystemExit("Tag, source and installed versions differ")
    if git("status", "--porcelain"):
        raise SystemExit("Release source worktree must be clean")
    if git("cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise SystemExit("An immutable annotated release tag is required")
    if git("rev-parse", "HEAD") != git("rev-parse", f"refs/tags/{tag}^{{commit}}"):
        raise SystemExit("HEAD differs from release tag target")
    remote = dict(
        line.split()[::-1]
        for line in git(
            "ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"
        ).splitlines()
    )
    if remote.get(f"refs/tags/{tag}") != git("rev-parse", f"refs/tags/{tag}") or remote.get(
        f"refs/tags/{tag}^{{}}"
    ) != git("rev-parse", "HEAD"):
        raise SystemExit("Remote tag object or target differs; never replace a published tag")
    print(f"Validated {tag} at {git('rev-parse', 'HEAD')}")


if __name__ == "__main__":
    main()
