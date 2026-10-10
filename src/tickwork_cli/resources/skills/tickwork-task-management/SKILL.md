---
name: tickwork-task-management
description: Manage this device's scheduled or manual Tickwork commands, upgrade Agent resources, and diagnose execution through run history and logs.
---

# Tickwork task management

Use for local task configuration, queries, execution and upgrade. Task definitions belong to this device; syncing a Vault does not deploy them elsewhere. Reuse known context and authorization; ask only for material missing intent.

## Workflow

```text
Task intent -> discover only unknown CLI contract
            -> manual: no native scheduler required
            -> scheduled: doctor / platform notes as needed
Configuration write -> preview -> authorized confirmation with actual plan
                    -> follow_up: test only with execution authorization
Execution -> this run's result / logs -> expected artifact verification
Upgrade -> package update -> registered Hint / Skill alignment -> verify version / upgrade.log
```

## Steps

1. Read `tickwork --help`, `tickwork task --help` and target command help only when the contract is unknown. Use `doctor` for scheduled tasks and [platform notes](references/platform-notes.md) for platform/session failures. A manual task uses `schedule.kind=manual`, has no native deployment, and works without a usable scheduler.
2. For an existing task, list/show before editing. For a new task obtain its absolute executable, argv, cwd, schedule mode and timeout. Do not invent credentials or commands. Use a JSON file according to CLI help.
3. Preview configuration changes; apply the actual plan with `--expected-plan` and `--confirm` when authorized. New scheduled tasks stay paused; manual tasks cannot pause/resume. Scheduled-to-manual removes owned native deployment; manual-to-scheduled starts paused. Ordinary schedule updates preserve paused state.
4. Consume actual returned `follow_up` entries. Creation or an execution-parameter change recommends testing, but does not authorize arbitrary code execution. When execution is authorized, preview the returned run command, inspect its current input, then execute with `--confirm`. Otherwise report the pending test. Follow-up commands retain the explicit `--home`; do not substitute another device or old approval hash. Testing never automatically resumes scheduling.
5. Inspect this run's result/log follow-ups, including failed runs, and verify expected artifacts. Exit 0 establishes process success only. Missing history can mean native launch failure; inspect native diagnostics. Do not claim remote push or AI output without evidence.
6. Do not modify foreign jobs. Running tasks reject edits/deletion; wait for completion rather than force killing. Do not elevate privileges, enable lingering, store passwords or add retries. When replacing a timer, test the new task with execution authorization, inspect deployment, stop the old entry before resuming the new one, and restore the prior entry on a failed handoff. Keep one recurring entry.

## Upgrade and resource registration

First resource registration uses `agent install` with verified absolute Hint and Skill paths. Preview and confirm according to authorization. The installer records destinations in this device's `local.yaml`, preserves unrelated Hint content, and rejects locally edited owned Skill files. Existing installs without registered destinations need explicit `agent install` once; do not scan or guess paths.

With upgrade authorization, run `tickwork upgrade`. Supported uv tool and pipx installations update through official PyPI in a detached process after the current CLI exits, then align resources using the new package. When `resources=deferred`, wait and inspect the returned `log_path`, package version, installed Skill and Hint; updater-spawned is not upgrade success. Offline, editable and unidentified installations report why package update was skipped and align registered resources only. Resource errors retain diagnostic evidence and do not imply all destinations were updated. Upgrade does not create, execute, enable or resume tasks; coordinate with running commands before replacing their environment. Do not call hidden internal upgrade flags as the ordinary user workflow.

## Storage

Use `~/.tickwork`, `TICKWORK_HOME`, or explicit `--home`. Back up `tasks.yaml` and `local.yaml`; native enabled state remains owned by the scheduler. SQLite is disposable run history/logs. Stop running commands and close CLI processes before deleting it; no format migrations or history restoration are supported.
