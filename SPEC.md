# Tickwork 工程规范

Tickwork 是本机定时任务管理 CLI。公开命令为 `tickwork`，发行包为 `tickwork-cli`；v0.1.0 支持 Linux systemd 用户 timer、macOS launchd GUI agent 和 Windows Task Scheduler 当前用户任务。发布验收证据见 CI，不能以安装成功代替原生调度验证。

## 产品与数据边界

- 每台设备独立配置和启用，不随 Vault 同步自动部署。不自建调度守护进程、Web UI、远程控制、工作流或 AI 会话编排。
- 命令是 argv 数组，无隐式 shell；可执行程序与工作目录为绝对路径。普通脚本、Campfire 和 AI CLI 使用同一执行机制。
- 支持 manual 模式，创建、查询、运行和删除不依赖原生调度器；pause/resume 明确不适用。定时转 manual 撤销受管部署，manual 转定时默认暂停。
- 三类时间规则：整分钟间隔（60..86400 秒）、每天时间、每周星期与时间；设备本地时区，原生 DST/休眠规则。无应用层补跑、自动重试或唤醒。
- 新建默认暂停，更新保留暂停状态；写操作预览与实际摘要确认。原生启用状态由系统查询，不在 YAML/SQLite 双写。
- `~/.tickwork/tasks.yaml` 是任务定义唯一事实源；`TICKWORK_HOME` 或 `--home` 覆盖目录。`tickwork.db` 保存可丢弃历史与日志；`.locks/` 是独立于数据库的 OS 运行锁。
- SQLite 删除重建，无旧格式兼容和迁移链。删除前停止运行；历史日志不恢复。日志每次最多 10 MiB，分块写入、分页查询，截断显式报告。完成历史保留 30 天/100 条，启动新运行时清理。
- 同任务不重叠；运行中修改/删除拒绝，避免平台卸载误杀进程。超时终止进程树。系统启动失败可能早于 SQLite 记录，须查原生日志。
- 仅管理带匹配本机路径及任务标识的系统配置。不开 lingering，不保存 Windows 密码，不升级权限。

## 工程边界

```text
CLI 参数与 JSON -> TaskService 用例 -> Scheduler Protocol -> 三个平台 adapter
                          |-> tasks.yaml Repository
                          |-> Runner -> SQLite Run Repository
Agent CLI -> Agent resource service -> 托管 Hint/Skill 文件
```

- CLI 不写业务规则，Service 不依赖 CLI 框架。标准库 argparse 负责参数发现，JSON Parser 负责单一输出契约；不保留第二套 Typer 文本输出。
- `app/task` 放任务业务；`app/agent` 只管理随包资源。`common` 放实际共享机制；ApplicationSettings 与 ApplicationContainer 按 MVC 模板组织，容器注入 Repository、Scheduler 和 Service，以 initialize/close 管理数据库生命周期；数据库按需连接，避免无关命令产生 SQLite。
- 不预建 BaseService/BaseRepository、Mapper、事件总线、历史版本接口或空模块。
- 公共帮助、无参数入口、版本、预览、成功和错误均为 UTF-8 JSON；stdout 成功/预览一个对象，stderr 错误一个对象及非零退出。日志/系统命令输出不得污染协议。
- 配置变更有 OS 锁、当前配置/原生状态摘要、原生失败补偿；不声称跨 YAML 和系统调度器原子事务。进程在写入期间被强杀时，以实际配置和原生状态诊断修复。
- Hint 只路由，Skill 只给 SOP，参数契约归 CLI JSON 帮助。资源升级仅修改托管范围，不启用任务。

## 升级与后续动作

- `tickwork upgrade` 更新受支持的 uv tool/pipx 包安装，再对齐 `local.yaml` 已登记的 Agent 资源。首次接入使用 agent install，不猜测旧安装位置。更新器等待当前 CLI 退出，输出写入本机 upgrade.log；启动更新器不能当成升级成功。
- 升级不写任务定义或改变启停状态，不迁移旧格式。离线、源码或未知安装方式只对齐已登记资源并报告跳过原因。更新内部参数隐藏，不进入公共帮助。
- 实际创建或修改执行参数后才返回测试 follow_up；执行后按真实 run_id 返回结果与日志入口，失败运行同样可诊断。follow_up 不自动执行，不沿用旧审批，创建不等于执行授权，测试不等于恢复调度。

## 验证与发布

运行 `uv run python scripts/quality_check.py`；入口/打包变化加 `--release`。类型检查覆盖当前系统及必要的其他平台目标。三平台原生创建、实际触发、日/周规则注册、启停、更新、删除及数据库重建由 CI 留证。带凭据 AI CLI 必须单独实测，不能用假 CLI 声称已验证。

v0.1.0 已按用户授权发布到 GitHub 与 PyPI。后续版本通过已配置的 Trusted Publisher 手动发布工作流执行；公开标签和已发布产物不可替换，实际上传成功后才能记录已发布。
