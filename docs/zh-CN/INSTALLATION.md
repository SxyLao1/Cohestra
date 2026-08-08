# 安装与接收方 Overlay

[English](../INSTALLATION.md)

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cohestra --version
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活。

Overlay 是针对一个已授权接收方或工作区、可审查的配置层。它可以选择 adapter、注册表项、guide 子集或健康策略，但不得携带凭据、会话标识、个人 Memory、隐式数据库路径、私有路由或桌面唤醒命令。

私有 recipient overlay 不进入 Git。仅提交已净化的公共默认值与示例；私有 overlay 通过已批准的本地路径分发。为 overlay 指定明确所有者，在使用前用已安装版本验证，并且只同步已批准的 guide 或注册表字段。

Workspace 子命令随版本变化。以 `cohestra workspace --help` 为准，绝不从用户主目录、桌面或已有本地数据库推断 overlay 位置。

```bash
cohestra adapters detect
cohestra adapters configure
cohestra adapters health
```

所有生成的 adapter overlay 初始均为 disabled/manual，且保持私有。未传 `--provider` 时，configure 选择已检测且非 `unsupported` 的 PATH 候选；默认不覆盖，拒绝 Git worktree 与 symlink。它减少手工路径与模板，但不创建桌面控制：审核实际 runtime，并由 recipient-local adapter 提供启动绑定。

| Provider | 支持状态 | Overlay 初始状态 |
| --- | --- | --- |
| Codex | manual-only | disabled/manual |
| Claude | headless candidate | disabled/manual |
| WorkBuddy | headless candidate | disabled/manual |
| ZCode | headless candidate | disabled/manual |
| Freebuff | 已收录/manual-only；automation unsupported | disabled/manual |

候选不是 delivery verified；只有关联 response 加 acknowledgement 才可能建立该结论，当前命令不做。
