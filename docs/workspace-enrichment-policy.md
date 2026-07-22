# Workspace enrichment policy

Workspace owners and administrators configure authoritative enrichment controls through:

- `GET /api/v1/workspaces/{workspace_id}/enrichment-policy`
- `PUT /api/v1/workspaces/{workspace_id}/enrichment-policy`

The policy stores tone, banned claims, required terminology, locked fields, maximum field lengths and
an optional per-run budget ceiling. Generation requests may add banned claims, required terms,
locked fields or lower maximum lengths, but they cannot weaken the workspace policy or raise its
budget. The system-wide budget ceiling remains authoritative when it is lower.

Policy changes are tenant-scoped, require CSRF protection for cookie sessions, require owner/admin
management permission and emit immutable audit events. If no workspace policy exists, request-level
controls continue to apply within system limits.
