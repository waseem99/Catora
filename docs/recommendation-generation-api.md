# Recommendation generation API

`POST /api/v1/workspaces/{workspace_id}/recommendations` runs the configured enrichment adapter,
validates structured output through the provider-neutral gateway and persists a new append-only
draft recommendation.

The endpoint requires the `recommendations.write` capability and CSRF protection for cookie
sessions. Product, variant and optional audit-finding identities are validated inside the requested
workspace before any provider call. Per-request budgets may be lower than the configured maximum
but cannot exceed it.

The built-in deterministic mock adapter is intended only for development and tests. It is disabled
by default and production configuration rejects it. A production provider adapter remains a
separate implementation. Provider failures do not create recommendation records, and successful
generations emit an immutable audit event with provider, model, prompt, cost and field-count
metadata.
