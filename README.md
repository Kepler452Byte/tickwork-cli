# Tickwork CLI

A clock tick starts the work. Tickwork manages scheduled commands on **this device**, with JSON output for agents and humans. Linux uses systemd user timers, macOS uses launchd GUI agents, and Windows uses Task Scheduler under the current user. MIT licensed.

No daemon, web UI, remote management or AI-specific runtime. Commands, scripts and AI CLIs use the same argv execution model.

## Install and discover

Python 3.12+ is required. Until the initial PyPI publication, install from GitHub:

```sh
uv tool install git+https://github.com/Kepler452Byte/tickwork-cli.git
tickwork --help
tickwork task --help
tickwork doctor
```

Every public response, including help and errors, is one UTF-8 JSON object. Success and previews use stdout; errors use stderr and a nonzero exit code. Child output is captured separately in SQLite. No implicit shell is used.

## Schedule a command

Write a JSON file with an absolute executable and working directory:

```json
{
  "id": "vault-sync",
  "argv": ["/home/user/.local/bin/campfire", "--workspace", "personal", "workspace", "git", "sync", "--confirm"],
  "cwd": "/home/user/vault",
  "schedule": {"kind": "interval", "seconds": 300},
  "timeout": 240
}
```

```sh
tickwork task create --file task.json
# Inspect the preview; use its actual plan hash:
tickwork task create --file task.json --expected-plan <hash> --confirm
# New tasks are paused. Test the command, then explicitly resume:
tickwork task run vault-sync --confirm
tickwork task resume vault-sync
tickwork task resume vault-sync --expected-plan <hash-from-resume> --confirm
tickwork task show vault-sync
tickwork task history --task vault-sync
tickwork task result <run-id>
tickwork task logs <run-id> --after 0 --limit 20
```

Update, pause and delete also preview and require the current plan hash. Updates preserve paused state. Busy tasks reject mutations; deletion never force-kills a running command. Same-task runs never overlap. Timeout kills the child process tree. Process exit zero does not prove the expected business artifact exists.

Intervals are native start-to-start, whole minutes 60..86400 seconds. Daily `{ "kind": "daily", "time": "09:00" }` and weekly `{ "kind": "weekly", "day": "mon", "time": "09:00" }` use device-local time and native DST rules. No retries, wake-up or application catch-up. launchd may coalesce missed calendar triggers on wake. See packaged [platform notes](src/tickwork_cli/resources/skills/tickwork-task-management/references/platform-notes.md).

The user scheduler/session must be available. Tickwork does not enable Linux lingering, create privileged services or save Windows credentials. `doctor` exposes session conditions and native diagnostics. Only matching ownership markers are managed.

## Local data and Agent resources

`~/.tickwork/` is the default; set `TICKWORK_HOME` or global `--home` to override. Back up `tasks.yaml`, the only durable task definitions. Native deployments are derived; actual enabled state comes from the scheduler. `tickwork.db` contains disposable run history and streamed stdout/stderr. `.locks/` contains OS-held runtime locks, independent of SQLite.

Logs are capped at 10 MiB per run and expose truncation. Finished history retains up to 100 records and 30 days, pruned on new runs. Pagination uses offsets for history and sequence cursors for logs. Delete DB/WAL files only with no running tasks; definitions and native deployments persist, historical logs do not recover. No migration chain or legacy formats.

Install the packaged Hint and single Skill explicitly into chosen destinations:

```sh
tickwork agent install --agents-file /absolute/AGENTS.md --skills-dir /absolute/skills
tickwork agent install --agents-file /absolute/AGENTS.md --skills-dir /absolute/skills --expected-plan <hash> --confirm
```

This preserves unrelated instructions/files, rejects locally edited Skill files, and never creates or enables tasks.

## Development and verification

```sh
uv sync --locked
uv run python scripts/quality_check.py --release
# Requires a working native user scheduler; creates and cleans only test-owned jobs:
RUN_NATIVE_TEST=1 uv run pytest -q tests/integration
```

CI runs quality, isolated wheel installation, native deployment and actual timer execution on Linux, macOS and Windows. Native evidence is uploaded per platform. Authenticated AI command execution is a separate local check; CI does not store AI credentials. PyPI publication is pending owner Trusted Publisher configuration.
