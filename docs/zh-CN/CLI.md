# CLI 参考

[English](../CLI.md)

包声明 `cohestra` 与 `cohestra-bridge` 两个入口。所有 bridge 命令都要求 `--db PATH`；输出为供机器消费的 JSON。alpha 基线以已安装版本的帮助输出为准。

```bash
cohestra --version
cohestra bridge --help
cohestra workspace --help
cohestra adapters detect
cohestra adapters configure
cohestra adapters health
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 task-create \
  --task-id demo-001 --title "Local demo" --agent coordinator
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
```

Bridge 提供任务准入与生命周期、事件、确认、工作声明、Leader 观测、升级、wake claim、snapshot 与 restore。恢复时使用显式 `--snapshot`、`--output`、`--rollback-output` 路径。

发布事件不等于唤醒 Agent。wake claim 只是一项可选 adapter 交接，bridge 从不执行事件正文。

未传 `--provider` 的 `configure` 选择已检测、非 `unsupported` 的 PATH 候选。它默认不覆盖，拒绝 Git worktree 与 symlink。所有生成的 overlay 初始均为 disabled/manual。候选检测不是唤醒验证：只有关联 response 加 acknowledgement 才能验证 delivery，当前命令不做该验证。

| Provider | 支持状态 |
| --- | --- |
| Codex | manual-only |
| Claude | headless candidate |
| WorkBuddy | headless candidate |
| ZCode | headless candidate |
| Freebuff | 已收录/manual-only；automation unsupported |
