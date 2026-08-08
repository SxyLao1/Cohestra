# Cohestra

[English](README.md)

[![CI](https://github.com/SxyLao1/Cohestra/actions/workflows/ci.yml/badge.svg)](https://github.com/SxyLao1/Cohestra/actions/workflows/ci.yml)

面向异构 AI Agent 的本地优先、可审计协作。

Cohestra 为共享工作区但不共享运行时、提供商或私有桌面控制面的 Agent 提供显式协作边界。协调状态保存在本地，可检查任务归属、事件、声明与升级证据。

## 状态

`0.1.0` 是 alpha 工程基线。schema-7 SQLite bridge、workspace 命令、adapter 合同和进程内 broker 已实现并完成本地测试。包内含五个 provider 的安全描述、检测与私有 overlay scaffold；具体启动绑定仍由接收方本地提供。GitHub 仓库和 CI 配置已公开；尚未发布 PyPI 包或 GitHub Release。

## 能力与边界

| 能力 | 边界 |
| --- | --- |
| 任务生命周期与准入 | 显式 task/agent 标识符的本地 SQLite bridge |
| 事件与确认 | 按 Agent 可见性和游标追加、读取与确认 |
| Leader 观测与升级 | 仅观测的租约状态和非敏感事件记录 |
| 工作与唤醒声明 | 原子声明；bridge 不执行私有唤醒命令 |
| 备份与恢复 | 显式 snapshot 与 rollback 输出路径 |
| 工作区注册表与 overlay | 选择性的、由接收方负责的配置合同 |
| 提供商中立 broker | 一个请求交给一个显式注册的进程内 adapter |

Wake adapter 是可选能力。发布 bridge 事件不等于唤醒请求，任何组件都不会把事件正文当作命令执行。

## 安装与快速开始

使用 Python 3.11 至 3.13，在本地检出中安装：

```bash
python -m pip install -e ".[dev]"
mkdir -p ./tmp/cohestra
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 task-create \
  --task-id demo-001 --title "Local demo" --agent coordinator
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
cohestra workspace validate \
  --registry ./examples/registry.json --guide ./examples/shared-guide.md
cohestra adapters detect
cohestra adapters configure
cohestra adapters health
```

Windows 可使用显式路径 `C:\Temp\cohestra\bridge.sqlite3`。bridge 不会发现数据库、注册表、凭据、会话或机器专属唤醒绑定。

未传 `--provider` 的 `cohestra adapters configure` 会在 `PATH` 中选择已检测且非 `unsupported` 的候选。默认不覆盖，并拒绝 Git worktree 与 symlink。它减少路径和模板的手工录入，但不是零配置桌面控制：实际 runtime 仍需用户审核，并由 recipient-local adapter 提供启动绑定。候选不等于已验证唤醒；只有关联 response 加 ack 才能称为 delivery verified，当前命令不做该验证。

## 文档

| 主题 | 链接 |
| --- | --- |
| 安装与接收方 overlay | [安装说明](docs/zh-CN/INSTALLATION.md) |
| CLI 参考 | [CLI 参考](docs/zh-CN/CLI.md) |
| 架构 | [架构](docs/zh-CN/ARCHITECTURE.md) |
| Adapter 合同 | [Adapter 指南](docs/zh-CN/ADAPTERS.md) |
| 安全边界 | [安全模型](docs/zh-CN/SECURITY_MODEL.md) |
| 发布流程 | [发布流程](docs/zh-CN/RELEASE.md) |

公开提取为单向净化提取，不含个人 Memory、活动数据库、凭据、会话标识、机器路径、私有路由或具体桌面唤醒绑定。详见[安全模型](docs/zh-CN/SECURITY_MODEL.md)。

请阅读 [Contributing](CONTRIBUTING.md)、[Security](SECURITY.md) 与[行为准则](CODE_OF_CONDUCT.md)。Cohestra 使用 [MIT License](LICENSE)。
