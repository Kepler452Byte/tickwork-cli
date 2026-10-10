---
name: tickwork-task-management
description: Manage this device's Tickwork scheduled commands and diagnose execution using native state, run history and logs.
---

# Tickwork task management

Use for creating, querying, updating, pausing, resuming, deleting or running local scheduled tasks. Task definitions are device-local; syncing a Vault does not deploy tasks elsewhere.

1. Discover the installed contract with `tickwork --help` and `tickwork task --help`, then the target subcommand help. Use `tickwork doctor` to check the native scheduler/session. Read [platform notes](references/platform-notes.md) when session, scheduling or native errors matter.
2. For an existing task, list/show before editing. For a new task obtain the intended executable and arguments, working directory, timing and timeout. Resolve the executable to an absolute path. Ask only for material missing intent; do not guess credentials or commands. Supply a JSON task file according to CLI help.
3. Mutating configuration previews by default. Inspect the returned plan. If the user has authorized the operation, confirm with its actual `--expected-plan`; otherwise present the preview and wait. Refresh a stale plan. Creating leaves the task paused; explicit resume is required. Resource installation never enables tasks.
4. Running executes arbitrary local code. A user request to execute authorizes manual `run --confirm`; preview otherwise. Scheduled runs are internal platform entry points, not an authorization bypass. For recurring work confirm scheduling intent before resume.
5. Verify show/native state after changes. Verify run history, result, paginated logs and expected artifacts after execution. Exit 0 establishes process success only. Missing history may mean native launch failure; inspect native diagnostics. Never report unverified remote push or AI output as completed.
6. Do not manage foreign system jobs. Busy tasks reject edits/deletion to avoid killing current execution; retry once the run completes. Do not force kill, enable lingering, request elevation, store passwords, add retries or replace existing timers without authorization.
7. If replacing a timer, first test the new task manually and inspect the native deployment, then stop the previous entry before resuming the new one. Preserve one recurring entry. On failure pause the new task and restore the prior timer, then report evidence.

Agent resources are explicitly installed using `agent install` with user-selected AGENTS file and skills directory. Preserve unrelated content. Reject locally edited owned files instead of overwriting them. Upgrades do not create, enable or resume tasks.

Storage: `~/.tickwork` or `TICKWORK_HOME`, overridden by global `--home`. Back up `tasks.yaml`. SQLite contains discardable historical runs and stdout/stderr. Deleting it loses history, not task definitions or native deployments. Do not delete DB while tasks are running. No format migrations are supported; this CLI maintains the current contract.
