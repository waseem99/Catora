# ADR 0013: Shopify GraphQL ingestion and credential references

## Status

Accepted

## Context

Catora needs a production-shaped Shopify catalog connection for controlled enterprise pilots. Raw access tokens must not be stored in source configuration, API payloads, source snapshots, logs, or error messages. Shopify catalog extraction must also support cursor recovery, incremental updates, and GraphQL query-cost limits.

## Decision

- Use the Shopify Admin GraphQL API version `2026-07`.
- Store only shop domain, API version, optional incremental timestamp, and a credential reference on `CatalogSource`.
- Resolve MVP credentials through `env:CATORA_CONNECTOR_SECRET_*` references behind a `SecretResolver` protocol.
- Keep the resolver replaceable by a managed secret-store implementation.
- Snapshot one complete Shopify product record with nested variants, options, media, collections, metafields, SEO, status, and timestamps.
- Use products cursor pagination and persist the cursor in the ingestion checkpoint.
- Use Shopify's `updated_at` search filter for incremental runs.
- Persist query-cost and throttle-state metadata in sanitized checkpoints and apply bounded backoff.
- Treat nested connections exceeding the bounded query limits as explicit warnings instead of silently claiming completeness.
- Never include the access token in `repr`, exceptions, API responses, or persisted payloads.

## Consequences

The initial connector is suitable for typical furniture and home catalogs and controlled pilots. Products with unusually large nested connections are flagged for follow-up hydration or a future Shopify Bulk Operations path. Environment references are appropriate for controlled deployments but are not the final enterprise secret-management implementation.
