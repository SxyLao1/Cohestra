# ADR 0001: Local-first explicit-path SQLite bridge

## Status

Accepted for the 0.1.0 architecture baseline.

## Decision

Use SQLite as durable coordination storage and require an explicit `--db` path. Keep task state, claims, cursors, leader observation, escalation, and recovery metadata in schema-governed tables.

## Consequences

State is local, inspectable, and easy to snapshot. Operators manage filesystem permissions and backups. SQLite WAL is not multi-host replication or identity enforcement.
