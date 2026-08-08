# CLI Reference

[简体中文](zh-CN/CLI.md)

The package declares `cohestra` and `cohestra-bridge`. All bridge commands require `--db PATH`; output is JSON for machine consumption. Installed help is authoritative for the alpha baseline.

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

The bridge exposes task admission and lifecycle, events, acknowledgements, work claims, leader observation, escalation, wake claims, snapshots, and restore. Use explicit `--snapshot`, `--output`, and `--rollback-output` paths for recovery.

Publishing an event does not wake an agent. A wake claim is only an optional
adapter handoff, and the bridge never executes event body text.

`configure` without `--provider` selects a detected, non-`unsupported` PATH
candidate. It defaults to no overwrite and rejects Git worktrees and symlinks.
All generated overlays begin disabled/manual. Candidate detection is not wake
verification: delivery requires a correlated response plus acknowledgement, and
the current commands do not perform that verification.

| Provider | Support |
| --- | --- |
| Codex | manual-only |
| Claude | headless candidate |
| WorkBuddy | headless candidate |
| ZCode | headless candidate |
| Freebuff | cataloged/manual-only; automation unsupported |
