# 架构

[English](../ARCHITECTURE.md)

Cohestra 将持久化协作事实与提供商专属执行分离。schema-7 SQLite bridge 在调用方指定的路径保存任务范围的元数据；Agent runtime 或 adapter 决定是否以及如何处理这些状态。

| 组件 | 职责 | 不负责 |
| --- | --- | --- |
| SQLite bridge | 任务、事件、游标、声明、Leader 观测、升级、恢复 | Agent 执行、凭据、提供商会话 |
| 工作区注册表 | 命名工作区与选择性的 guide/sync/health 输入 | 个人 Memory 或活动 bridge 发现 |
| Recipient overlay | 接收方专属、可审查的配置 | 私有路由或秘密注入 |
| Adapter | 在本地策略下执行 provider/runtime 动作 | 修改 schema 或隐式提权 |
| 有限 broker | 在明确退出前协调 adapter 尝试 | 常驻服务、云调度、桌面控制 |

## 不变量

- 每次 bridge 操作都使用显式状态路径。
- 声明在 adapter 动作前必须是任务范围内的持久状态。
- 观测不能改变领导权或其他 Agent 的游标。
- 升级只保存非敏感证据指针，不保存秘密或原始对话。
- Restore 需要独立的 rollback 目标。
- 已发布事件只是数据，不是唤醒请求，也不是可执行命令正文。
- 可选 wake adapter 缺失或不符合资格时，以 unsupported 失败关闭。

SQLite WAL 支持本地协作，不是多主机复制或身份控制。升级含活动工作项的 bridge 前先备份。
