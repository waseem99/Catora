# Recommendation query API

Catora exposes tenant-scoped, read-only recommendation endpoints:

- `GET /api/v1/workspaces/{workspace_id}/recommendations`
- `GET /api/v1/workspaces/{workspace_id}/recommendations/{recommendation_id}`

The list endpoint supports product, status and task filters with exact `total`, `offset` and
`limit` metadata. Results are ordered newest first and fields are ordered deterministically by
field key. Both responses include the immutable source snapshot hash, provider and prompt identity,
cost, execution metadata, original/proposed/edited values, evidence, deterministic confidence,
verification state and proposal metadata.

Workspace membership is checked before data lookup. A recommendation outside the requested
workspace is returned as `404`, avoiding cross-tenant existence disclosure. These endpoints do not
mutate recommendations or invoke an AI provider.
