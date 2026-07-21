# ADR 0002: Tenant scoping, provenance and immutable versions

- **Status:** Accepted
- **Date:** 2026-07-21

## Decision

1. Every business record is scoped to a workspace. Organization, workspace, user and membership records are the only exceptions.
2. Repository constructors require a workspace identifier and expose no unscoped entity-list operation.
3. Raw source records are retained separately from canonical products. Canonical values reference source evidence rather than replacing raw values.
4. Taxonomy and rule versions become immutable after use in an audit. Audits record their exact source snapshot and rule-version set.
5. Generated recommendations retain model, provider, prompt version, cost, evidence and source snapshot.
6. Audit events are append-only. Operational entities may use `deleted_at`; evidentiary and historical entities are retained according to workspace policy.

## Consequences

- Cross-workspace reads require an explicit programming error or security defect rather than an omitted optional filter.
- Historical audit results remain reproducible after taxonomy, rule or source changes.
- Storage use is higher because raw snapshots and historical recommendations are retained.
- Destructive hard deletion requires a governed retention workflow rather than ordinary CRUD.
