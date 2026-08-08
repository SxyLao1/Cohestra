# Cohestra

Local-first, auditable coordination for heterogeneous AI agents.

Cohestra provides a small, explicit coordination boundary for agents that share
a workspace but do not share a runtime, provider, or private desktop control
plane. It records coordination state locally so task ownership, events, claims,
and escalation evidence can be inspected and backed up.

## Status

`0.1.0` is an alpha engineering baseline. The schema-7 SQLite bridge,
workspace commands, adapter contracts, and in-process broker are implemented
and locally tested. Recipient-specific provider adapters remain intentionally
outside the package. This repository has not been remotely validated, released,
or published.

## Capabilities

| Capability | Boundary |
| --- | --- |
| Task lifecycle and admission | Local SQLite bridge with explicit task and agent identifiers |
| Events and acknowledgements | Append/read with per-agent visibility and cursors |
| Leader observation and escalation | Observation-only lease state and non-sensitive incident records |
| Work and wake claims | Atomic claims; adapters execute no private wake command for the bridge |
| Backup and restore | Explicit snapshot and rollback output paths |
| Workspace registry and overlays | Selective, recipient-owned configuration contract |
| Provider-neutral broker | One request to one explicitly registered in-process adapter |

## Install and Quickstart

Use Python 3.11 through 3.13. Install from a local checkout while the project
is pre-release:

```bash
python -m pip install -e ".[dev]"
mkdir -p ./tmp/cohestra
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 init
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 task-create \
  --task-id demo-001 --title "Local demo" --agent coordinator
cohestra-bridge --db ./tmp/cohestra/bridge.sqlite3 health
cohestra workspace validate \
  --registry ./examples/registry.json --guide ./examples/shared-guide.md
```

On Windows, an equivalent explicit path is `C:\Temp\cohestra\bridge.sqlite3`.
The bridge does not discover databases, registry files, credentials, sessions,
or machine-specific wake bindings.

## Architecture

```text
Agent runtimes -> explicit adapter contracts -> finite broker (optional)
                                               |
                                               v
                                    schema-7 SQLite bridge
                                               ^
                                               |
                         selective registry, guides, and recipient overlays
```

The bridge owns coordination records, not agent execution. Adapters own their
provider and local launch behavior. See [Architecture](docs/ARCHITECTURE.md)
and [Adapter Guide](docs/ADAPTERS.md).

## Security Boundary

The public extraction is one-way and sanitized. It excludes personal memory,
live databases, credentials, session identifiers, machine paths, private routes,
and concrete desktop wake bindings. Cohestra is not an identity provider,
secret manager, remote control plane, or authorization system for arbitrary
local commands. Read the [Security Model](docs/SECURITY_MODEL.md).

## Compatibility

The package declares Python 3.11, 3.12, and 3.13 support. Its bridge database
is local SQLite and should be accessed only through a compatible Cohestra
version. Cross-platform behavior belongs at adapter boundaries; no desktop wake
mechanism is portable by default.

## Documentation

| Topic | Link |
| --- | --- |
| Installation and recipient overlays | [Installation](docs/INSTALLATION.md) |
| Minimal recipient examples | [Examples](examples/README.md) |
| CLI reference | [CLI Reference](docs/CLI.md) |
| Architecture | [Architecture](docs/ARCHITECTURE.md) |
| Adapter contract | [Adapter Guide](docs/ADAPTERS.md) |
| Security boundary | [Security Model](docs/SECURITY_MODEL.md) |
| Release process | [Release Process](docs/RELEASE.md) |
| Engineering history | [Worklog](WORKLOG.md) |

## Contribution and Governance

See [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), and the [Code of
Conduct](CODE_OF_CONDUCT.md). No open-source license has been selected. Do not
assume reuse, redistribution, or contribution rights beyond separately granted
permission.
