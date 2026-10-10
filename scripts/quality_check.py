import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    commands = [
        ["ruff", "check", "src", "tests", "scripts"],
        ["ruff", "format", "--check", "src", "tests", "scripts"],
        ["mypy", "src"],
        ["pytest", "-q"],
    ]
    for command in commands:
        subprocess.run([sys.executable, "-m", *command], cwd=ROOT, check=True)
    if args.release:
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/smoke"],
            cwd=ROOT,
            check=True,
            env={**__import__("os").environ, "RUN_WHEEL_TEST": "1"},
        )


if __name__ == "__main__":
    main()
