# Changelog

## 0.2.2

- Align agent_resources and system with the MVC template, retaining JSON argparse discovery and lazy SQLite. Registered resources follow packaged content; preserve Hint exterior bytes and user files, clean retired attachments and retain existing explicit locations.
- Preview and confirm package upgrades, detect uv tool/pipx receipts, persist queryable operation stages, verify the new CLI and resource alignment, and preserve Windows background execution. Expose offline --skip-package alignment.
- Add configurable per-task success/failure retention, previewed filtered cleanup with failure preservation and cascading logs, orphan reconciliation under run locks, and separate safe SQLite compaction.
- Keep UTC timestamps and add UTC/local/IANA display_time to history/result, with cross-platform tzdata.

## 0.2.1

- Run newly registered Windows scheduled tasks through the same environment's pythonw.exe, avoiding a console window for the runner.
- Suppress console windows for task and scheduler helper processes; keep captured logs and exit status when standard streams are absent. Task input is EOF for unattended execution.
- Document re-registering existing Windows tasks after upgrade while preserving enabled/paused state; missing pythonw.exe is a deployment error.

## 0.2.0 — 2026-10-10

- Add package/resource upgrade with explicit registered Agent destinations, detached update logs and preserved task state.
- Add structured follow-up testing and per-run result/log commands without automatic execution.
- Add manual-only tasks without native deployment; scheduled/manual transitions preserve explicit activation requirements.
- Align Settings, Container, repository injection and resource lifecycle with the MVC template; retain the SQLite implementation and JSON CLI.

## 0.1.0 — 2026-10-10

- Manage device-local interval, daily and weekly commands through Linux systemd, macOS launchd and Windows Task Scheduler.
- JSON discovery, previews and errors; paused creation, native enabled state, scoped ownership and stale-plan protection.
- Manual runs, bounded streaming SQLite logs, paginated history/results, timeout process-tree termination and overlap prevention.
- Durable YAML definitions with disposable SQLite; no legacy formats or migrations.
- Packaged Agent Hint and task-management Skill, explicitly installed without activating tasks.

Published on [PyPI](https://pypi.org/project/tickwork-cli/0.1.0/) and [GitHub](https://github.com/Kepler452Byte/tickwork-cli/releases/tag/v0.1.0). [Release workflow](https://github.com/Kepler452Byte/tickwork-cli/actions/runs/38038458653) verified native scheduling on all three platforms; actual PyPI distributions passed hash and isolated installation checks. Authenticated AI execution was tested on Linux, without claiming macOS/Windows credential verification.
