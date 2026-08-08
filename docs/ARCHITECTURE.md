# Architecture

Cohestra separates durable coordination facts from provider-specific execution. The schema-7 SQLite bridge stores task-scoped metadata at a caller-supplied path. An agent runtime or adapter decides whether and how to act on that state.

| Component | Responsibility | Exclusion |
| --- | --- | --- |
| SQLite bridge | Tasks, events, cursors, claims, leader observation, escalation, recovery | Agent execution, credentials, provider sessions |
| Workspace registry | Named workspace and selective guide/sync/health inputs | Personal memory or live bridge discovery |
| Recipient overlay | Recipient-specific, reviewable configuration | Private routes or secret injection |
| Adapter | Provider/runtime action under local policy | Schema mutation or implicit privilege escalation |
| Finite broker | Validate and dispatch one request to one registered adapter | Discovery, retry daemon, cloud scheduler, desktop control |

## Invariants

- Every bridge operation uses an explicit state path.
- Claims are task-scoped and durable before adapter action.
- Observation does not change authority or another agent's cursor.
- Escalations hold non-sensitive evidence pointers, not secrets or transcripts.
- Restore requires a distinct rollback destination.

SQLite WAL supports local coordination, not multi-host replication or identity enforcement. Back up before upgrading a bridge with active work.
