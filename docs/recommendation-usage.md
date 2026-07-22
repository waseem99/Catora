# Recommendation usage reporting

`GET /api/v1/workspaces/{workspace_id}/recommendation-usage` reports reconciled
AI-enrichment usage from persisted recommendations.

The response includes recommendation count, linked completed asynchronous-job count,
input tokens, output tokens, monetary cost in microunits and a deterministic provider/model
breakdown. The same endpoint becomes product-level reporting when `product_id` is supplied.

Optional `provider`, `created_from` and exclusive `created_before` filters apply identically
to totals and provider/model rows. Product filters are validated inside the workspace before
usage is queried, so cross-tenant identifiers return a non-disclosing `404`.

Historical recommendations with absent or malformed token metadata remain reportable and
contribute zero tokens. Costs and counts remain derived from stored deterministic records;
no provider call or LLM-derived metric is used for reporting.
