# Tickwork 工程规范

Tickwork 是面向用户与 Agent 的本机定时任务管理 CLI，基于 Typer MVC 模板。当前只提供版本入口；调度管理属于待实现范围，不能描述为既有能力。

## 产品边界

- 每台设备独立配置和启用；不随 Vault 同步任务，不自动开启其他设备。
- 目标使用 Linux systemd、macOS launchd、Windows Task Scheduler；不自行实现调度守护进程。
- 普通命令、脚本和 AI CLI 共用命令执行模型，不维护模型调用或 Agent 会话编排。
- 只管理自身标识的任务，不接管未知系统任务；不提供 Web UI、远程控制和工作流编排。
- 尚未建立任务存储；不预建数据库、迁移链或重复保存系统调度事实的状态模型。

## 工程边界

```text
CLI 参数与输出 -> Service 用例 -> 平台调度适配器
```

- 按业务模块组织 `app/`；CLI 不写业务规则，Service 不依赖 Typer。
- `common/` 仅放共享技术机制；跨模块依赖在组合根装配，实际需要时才增加组合根。
- 不预建 BaseService、BaseRepository、Mapper、事件总线或无消费方的接口。
- 文件使用 `{resource}_{type}.py`，只维护当前结构，不增加历史格式兼容分支。
- 所有公共命令输出统一 JSON，包括无参数帮助、`--help`、version、预览、成功结果与错误；成功 stdout 只输出一个 JSON 对象，错误 stderr 只输出一个 JSON 对象并使用非零退出码。不增加第二套文本输出、交互提示或 ANSI 内容；子进程日志不得混入命令结果。
- 当前只有 version 已输出 JSON；模板原生 help 尚未对齐上述契约，须在首次功能交付前补齐。任务日志查询的输出封装在 JSON 内，不直接混入原始输出流。
- 写操作实施时提供预览与显式确认；系统配置写入须处理并发变化及失败补偿，不承诺跨资源原子事务。

## 验证

修改 Python 行为运行 `uv run python scripts/quality_check.py`；入口或打包变化运行 `--release`。平台支持必须有原生执行证据，不能以单平台测试宣称三平台已支持。初始化与开发不授权外部发布。
