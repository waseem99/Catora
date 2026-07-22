# ADR 0012: CSV ingestion job lifecycle

## Status

Accepted

## Context

Catora must accept enterprise catalog exports without requiring storefront credentials. CSV is the fastest paid-diagnostic path, but ingestion still needs tenant isolation, resumability, row-level rejection, idempotency, background execution, and auditable job state.

## Decision

- Store uploaded CSV objects in workspace-scoped S3-compatible keys.
- Persist immutable source snapshots in `SourceRecord` with deterministic content hashes.
- Execute ingestion through Celery and Redis using explicit job states.
- Commit each completed connector page so jobs can resume from a durable checkpoint.
- Count valid source rows independently from newly inserted snapshots; unchanged reruns are successful but deduplicated.
- Keep bounded rejection samples internally for diagnostics, while ordinary job responses expose only sanitized checkpoint fields.
- Require workspace membership, role authorization, CSRF protection, upload size limits, and audit events for all ingestion writes.
- Never allow a connector, source, and job from different workspaces or source types to execute together.

## Consequences

The CSV path can support real paid diagnostics before Shopify OAuth is available. Page-level commits slightly reduce throughput compared with one large transaction, but provide safer recovery and visible progress. Raw rejected rows remain restricted because they may contain commercially sensitive product data.
