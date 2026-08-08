# Adapter 指南

[English](../ADAPTERS.md)

Adapter 将 Cohestra 协调状态连接到某个 provider 或本地 runtime。它有意位于 SQLite bridge 外部。bridge 可以记录原子 wake claim，但不会调用 adapter，也不知道私有桌面命令。

Adapter 应声明稳定标识和支持的 runtime，验证任务范围输入，应用本地 allowlist，在不记录秘密的前提下保留关联标识，并区分 unsupported、启动前失败、已派发和未知投递结果。

| Provider | 公开支持状态 | Overlay 初始状态 |
| --- | --- | --- |
| Codex | manual-only | disabled/manual |
| Claude | headless candidate | disabled/manual |
| WorkBuddy | headless candidate | disabled/manual |
| ZCode | headless candidate | disabled/manual |
| Freebuff | 已收录/manual-only；automation unsupported | disabled/manual |

`detect` 识别安全候选，`configure` 创建私有 overlay scaffold。未传 `--provider` 时，configure 在 `PATH` 中选择已检测且非 `unsupported` 的候选；默认不覆盖，并拒绝 Git worktree 和 symlink。它减少路径和模板录入，不代替 runtime 审核：接收方必须提供并审核实际本地启动绑定。

Adapter 不得从个人目录、浏览器 profile 或活动数据库发现状态；不得在公共配置内嵌凭据、会话、私有路由或机器专属唤醒绑定；不得执行任意事件正文。Wake 支持是可选的：adapter 不存在、不符合资格或不能验证请求时，必须以 unsupported 失败关闭，不得派发回退命令。

```text
Leader event -> bridge wake claim -> adapter validation -> local dispatch
     ^                                                   |
     +------- claim result: dispatched or launch_failed--+
```

投递确认依赖 provider，完成本地派发后仍可能未知。发布事件不表示唤醒请求。Unsupported 是有效的跨平台健康结果；不要提供会尝试私有桌面唤醒命令的通用回退。

候选不等于已验证唤醒。只有记录关联 response 与 acknowledgement 才能称 delivery verified；当前命令不执行该验证。
