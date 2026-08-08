# Security Policy

## Scope

Cohestra coordinates local agent work through an explicit SQLite path. Reports
may cover bridge schema, CLI input, backups/restores, adapter contracts, and
sanitized workspace extraction. Unsupported provider APIs and user-operated
local commands are out of scope.

## Reporting

Do not open a public issue for a suspected vulnerability. Contact the project
owner through an approved private channel with a minimal reproduction, affected
version or commit, impact, and safe remediation idea. Do not send live databases,
credentials, access tokens, personal memory, or private route details.

## Operational guidance

Treat the bridge database as sensitive coordination metadata. Restrict its
directory to intended local users, use explicit backup destinations, validate a
snapshot before restore, and review adapter configuration before enabling an
external action.
