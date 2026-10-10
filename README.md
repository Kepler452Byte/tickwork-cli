# Tickwork CLI

Tickwork（滴答声推动工作）是独立的本机定时任务管理 CLI，基于 `typer-cli-mvc-template` 初始化。

- 发行包及项目：`tickwork-cli`
- Python 包：`tickwork_cli`
- 命令：`tickwork`

当前仅完成项目骨架和版本入口，尚未实现定时任务管理。

```bash
uv sync --locked
uv run tickwork version
uv run tickwork --help
uv run python scripts/quality_check.py --release
```

目标是统一管理本机系统调度器中的受管任务，支持普通命令、脚本和 AI CLI；设备独立配置，不随 Vault 同步启用。不提供 Web UI、远程控制或常驻调度进程。已有 Campfire 同步任务尚未接管。
