# ADR 0011: Catalog connector contract

- Status: Accepted
- Date: 2026-07-21
- Parent issue: #5

## Context

Catora must ingest Shopify, CSV, sitemap, and bounded public URL sources without coupling the normalization and audit pipeline to provider-specific payloads. Imports must also resume safely after interruption and retain row-level failures instead of discarding an entire catalog.

## Decision

All catalog sources implement the asynchronous `CatalogConnector` contract. A connector validates its configuration and yields bounded `ConnectorPage` values containing accepted records, row-level rejections, and a serializable next checkpoint.

Each accepted record includes a stable external identifier, record type, raw mapped payload, deterministic SHA-256 content hash, optional source timestamp, and warnings. Connectors do not write directly to canonical product tables; persistence and normalization remain separate orchestration responsibilities.

The first implementation is the CSV connector because it supports sales demonstrations and paid diagnostics without requiring client API credentials. It provides column discovery, required mapping validation, delimiter detection, row-level rejection, deterministic hashing, bounded pages, and checkpoint resume.

## Consequences

- Shopify and crawler implementations must pass the same connector contract tests.
- Checkpoints describe the next safe resume boundary and must remain JSON serializable.
- Content hashes make unchanged source records idempotent when persisted.
- Connector-specific transformations stay shallow; canonical normalization remains in Issue #6.
- CSV files with invalid required mappings fail validation, while invalid individual rows are rejected independently.

## Security and limits

Connectors must not log credentials or sensitive headers. Public crawling will remain bounded and authorization-confirmed. Page sizes are bounded to prevent accidental memory exhaustion.
