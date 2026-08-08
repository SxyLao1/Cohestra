# Security Model

The bridge database can contain task titles, participants, coordination events, claim state, and evidence pointers. Recipient overlays contain local policy choices. Neither is an appropriate place for secrets.

- The SQLite path and filesystem permissions are operator-managed.
- The bridge validates state transitions but does not authenticate an OS user or remote provider.
- An adapter is a separate trust boundary and must apply local allowlists.
- A finite broker has no implicit wake, scheduling, credential, or network privilege.

Public materials are selectively extracted one-way from a customized local workspace. They exclude personal memory, live databases, credentials, session IDs, machine paths, private routes, and concrete desktop wake bindings.

Use restrictive filesystem permissions, explicit test paths, reviewable overlays, non-sensitive escalation pointers, validated snapshots, and a rollback path for restore. Cohestra does not provide hosted tenancy, cryptographic identity, secret storage, endpoint management, remote command execution, or delivery guarantees.
