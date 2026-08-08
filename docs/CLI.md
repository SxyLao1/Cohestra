# CLI Reference

The package declares `cohestra` and `cohestra-bridge`. All bridge commands require `--db PATH`; output is JSON for machine consumption. Installed help is authoritative for the alpha baseline.

```bash
cohestra --version
cohestra bridge --help
cohestra workspace --help
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 task-create \
  --task-id demo-001 --title "Local demo" --agent coordinator
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
```

The bridge exposes task admission and lifecycle, events, acknowledgements, work claims, leader observation, escalation, wake claims, snapshots, and restore. Use explicit `--snapshot`, `--output`, and `--rollback-output` paths for recovery.
