# 安全模型

[English](../SECURITY_MODEL.md)

Bridge 数据库可能包含任务标题、参与者、协调事件、声明状态和证据指针。Recipient overlay 包含本地策略选择。两者都不应保存秘密。

- SQLite 路径及其文件系统权限由操作方管理。
- Bridge 校验状态迁移，但不认证操作系统用户或远程 provider。
- Adapter 是独立信任边界，必须实施本地 allowlist。
- 有限 broker 没有隐式唤醒、调度、凭据或网络权限。

公开材料来自经选择的一次性净化提取，不含个人 Memory、活动数据库、凭据、会话 ID、机器路径、私有路由和具体桌面唤醒绑定。

使用受限文件权限、显式测试路径、可审查 overlay、非敏感升级指针、已验证 snapshot 及 restore rollback 路径。Cohestra 不提供托管租户、密码学身份、秘密存储、终端管理、远程命令执行或投递保证。

私有 overlay 不进入 Git。发布事件不是唤醒 Agent 或执行正文的授权。Wake adapter 是可选能力；adapter 缺失或不符合资格时，以 unsupported 失败关闭。
