# Tickwork CLI

A clock tick starts the work. Tickwork manages scheduled commands on **this device**, with JSON output for agents and humans. Linux uses systemd user timers, macOS uses launchd GUI agents, and Windows uses Task Scheduler under the current user. MIT licensed.

No daemon, web UI, remote management or AI-specific runtime. Commands, scripts and AI CLIs use the same argv execution model.

## Install and discover

Python 3.12+ is required. Install the published package from PyPI:

```sh
uv tool install tickwork-cli
tickwork --help
tickwork task --help
tickwork doctor
tickwork upgrade
```

Every public response, including help and errors, is one UTF-8 JSON object. Success and previews use stdout; errors use stderr and a nonzero exit code. Child output is captured separately in SQLite. No implicit shell is used.

## Upgrade and follow-up actions

`tickwork upgrade` previews supported uv tool/pipx package replacement and registered resource changes. Apply with `--expected-plan <expected_plan>` and `--confirm`. Editable or unknown installations report their channel and reject package-update confirmation; use public `--skip-package` to preview and confirm offline resource alignment. An external worker waits for this CLI to exit, verifies the installed package version, aligns resources through that package and checks for zero pending operations.

A scheduled response is not completion. Query `tickwork agent upgrade-status <operation_id>` until `state` is `completed` or `failed`; package and resource stages are reported separately. Failure returns a nonzero exit code. Diagnostic logs are scoped to `~/.tickwork/upgrades/<operation_id>/updater.log`, without raw package-manager output. Upgrade preserves task definitions and native enabled state.

When upgrading from v0.2.1, use the original package manager (`uv tool upgrade tickwork-cli` or `pipx upgrade tickwork-cli`), verify `tickwork version`, then preview `tickwork agent sync` and confirm its current plan. The previous updater does not confirm the new resource preview, so package installation alone does not establish resource alignment.

`local.yaml` records explicitly supplied resource destinations and owned files. Existing registered locations and `.tickwork-owned.json` ownership records are retained and consolidated on confirmed sync. Installs without registration require explicit paths once; no directory discovery occurs.

Successful creation or execution-parameter updates return a `follow_up` run preview for the actual task. Execute only with user execution authorization; creation alone is insufficient. Run output returns result/log commands for the actual run, including failures. Follow-ups are guidance, never automatic execution or schedule activation.

## Manual-only commands

Use `"schedule": {"kind": "manual"}` to reuse a command, timeout and run history without native scheduling. The field remains required. Manual create/show/run/update/delete do not require a usable native scheduler; pause/resume report that scheduling is not applicable. Changing scheduled to manual removes owned deployment; changing back to a schedule starts paused. No once or cron expressions are introduced.

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

## Windows background execution

From v0.2.1, newly registered Windows tasks use `pythonw.exe` from the same Python environment, and console commands started by Tickwork run without a console window. That environment must include `pythonw.exe`; deployment reports an error if it is missing. Task stdin is closed (EOF); commands must run unattended. Output and exit status remain available through `task history`, `task result` and `task logs`. Applications that explicitly open their own GUI windows control those windows themselves.

Package upgrade preserves existing Task Scheduler registrations. To apply the new entry point to an existing scheduled task, export its current definition with PowerShell and update it unchanged:

```powershell
$id = 'your-task-id'
$shown = tickwork task show $id | ConvertFrom-Json
$definition = $shown.task | Select-Object id, argv, cwd, schedule, timeout
$file = Join-Path $env:TEMP "tickwork-$id.json"
$json = $definition | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($file, $json, [System.Text.UTF8Encoding]::new($false))
$preview = tickwork task update --file $file | ConvertFrom-Json
# Inspect the definition, scheduler_before and enabled_after before confirming.
tickwork task update --file $file --expected-plan $preview.plan --confirm
tickwork task show $id
Remove-Item $file
```

Use the same global `--home` on every command if your task uses a custom state directory. Update each scheduled task separately; updating preserves its existing enabled/paused state and rejects running tasks. Wait for the next trigger to verify the change. A paused task stays paused until explicitly resumed. Failures before a run is recorded are diagnosed through Task Scheduler's LastTaskResult and Operational log.

## Local data and Agent resources

`~/.tickwork/` is the default; set `TICKWORK_HOME` or global `--home` to override. Back up `tasks.yaml`, the only durable task definitions. Native deployments are derived; actual enabled state comes from the scheduler. `tickwork.db` contains disposable run history and streamed stdout/stderr. `.locks/` contains OS-held runtime locks, independent of SQLite.

Logs are capped at 10 MiB per run and expose truncation. Retention applies separately to each task: successful runs default to 7 days/100 records; failed, timed-out and interrupted runs default to 30 days/100 records, keeping at least the latest 10 failures. Count caps take priority over the minimum. Age means rolling 24-hour days since completion in UTC. Cleanup runs before and after execution, retaining the just-returned result until the next cleanup; a stopped task can be cleaned explicitly. Customize with `TICKWORK_SUCCESS_DAYS`, `TICKWORK_FAILURE_DAYS`, `TICKWORK_SUCCESS_LIMIT`, `TICKWORK_FAILURE_LIMIT` and `TICKWORK_FAILURE_KEEP`. The separate buckets prevent high-frequency successes from displacing failure diagnostics. At the 10 MiB log maximum, 200 retained runs can use about 2 GiB **per task**, so lower caps for noisy tasks.

```sh
# Preview deleting successes finished at least seven days ago, preserving failures:
tickwork task cleanup --task vault-sync --older-than 7 --keep-failures
tickwork task cleanup --task vault-sync --older-than 7 --keep-failures --expected-plan <plan> --confirm
# Without --older-than, apply configured retention. --status is repeatable.
tickwork task cleanup
# Logical deletion cascades logs; reclaim file space separately when no tasks are running:
tickwork task compact
tickwork task compact --expected-plan <plan> --confirm
# UTC originals remain unchanged; display_time adds offset-aware representations:
tickwork task history --timezone Asia/Shanghai
tickwork task result <run-id> --timezone local
```

An explicit `--older-than` overrides default age/minimum/count policy for the filtered records; use `--keep-failures` to preserve all failure classes. Running records are excluded. Confirmed cleanup marks orphan running records interrupted only after obtaining their task's OS lock; these are retained for a subsequent cleanup. Cleanup previews do not reconcile records. Compaction takes all task locks and rejects active runs; it does not run on each trigger. Both commands leave task definitions and scheduling unchanged.

Pagination uses offsets for history and sequence cursors for logs. Default time display is UTC; `local` or an IANA zone affects only the added `display_time` field. Packaged tzdata supports Windows. Native schedules continue using device local time. Delete DB/WAL files only with no running tasks; definitions and native deployments persist, historical logs do not recover. No migration chain or legacy database formats.

Install the packaged Hint and single Skill explicitly into chosen destinations:

```sh
tickwork agent install --agents-file /absolute/AGENTS.md --skills-dir /absolute/skills
tickwork agent install --agents-file /absolute/AGENTS.md --skills-dir /absolute/skills --expected-plan <hash> --confirm
```

Registered files follow the package, including local edits inside owned Skill files and the Hint block. Preview those replacements before confirming. Bytes outside the Hint block and user-added files are preserved; package-removed owned files are cleaned. Unregistered conflicting files, malformed markers and changes after preview block writes. `--hint-file` also accepts the Hint path; `--agents-file` remains an alias. Hint and Skill targets can be installed independently. `agent sync` previews alignment of all registered targets; repeated confirmed sync is a zero-write operation. Resource commands never create or enable tasks.

## Development and verification

```sh
uv sync --locked
uv run python scripts/quality_check.py --release
# Requires a working native user scheduler; creates and cleans only test-owned jobs:
RUN_NATIVE_TEST=1 uv run pytest -q tests/integration
```

CI runs quality, isolated wheel installation, native deployment and actual timer execution on Linux, macOS and Windows. Native evidence is uploaded per platform. Authenticated AI command execution is a separate local check; CI does not store AI credentials. [v0.1.0 is published on PyPI](https://pypi.org/project/tickwork-cli/0.1.0/). Releases use the configured Trusted Publisher workflow.
