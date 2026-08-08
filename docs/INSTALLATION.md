# Installation and Recipient Overlays

[简体中文](zh-CN/INSTALLATION.md)

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cohestra --version
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

An overlay is a reviewable layer for one authorized recipient or workspace. It may select an adapter, registry entry, guide subset, or health policy. It must not carry credentials, session identifiers, personal memory, implicit database paths, private routes, or desktop wake commands.

Keep private recipient overlays out of Git. Commit only sanitized public defaults
and examples; distribute private overlay material through an approved local path.

Keep public defaults in version control, assign explicit ownership, validate the overlay against its installed version, and synchronize only approved guide or registry fields. Use `cohestra workspace --help` as the installed command authority, and never infer an overlay location from a user home, desktop, or existing local database.

Start from the neutral files under `examples/`, then replace identifiers and
paths in a private recipient-owned overlay. Validate it before any sync:

```bash
cohestra workspace validate \
  --registry ./examples/registry.json --guide ./examples/shared-guide.md
cohestra workspace sync \
  --playbooks ./playbooks --skills ./recipient-skills --link-mode manual
cohestra adapters detect
cohestra adapters configure
cohestra adapters health
```

All generated adapter overlays start disabled/manual and remain private. Without
`--provider`, configure selects a detected non-`unsupported` PATH candidate;
it does not overwrite by default and rejects Git worktrees and symlinks. This
reduces manual paths and templates, but does not create desktop control: review
the runtime and provide a recipient-local launch adapter.

| Provider | Support | Initial overlay |
| --- | --- | --- |
| Codex | manual-only | disabled/manual |
| Claude | headless candidate | disabled/manual |
| WorkBuddy | headless candidate | disabled/manual |
| ZCode | headless candidate | disabled/manual |
| Freebuff | cataloged/manual-only; automation unsupported | disabled/manual |

A candidate is not delivery verified;
only a correlated response plus acknowledgement could establish that, and the
current commands do not do so.
