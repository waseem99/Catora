# Buyer-intent category coverage and remediation analytics

A completed saved intent-suite run exposes two deterministic read-only analytics endpoints:

- `GET /api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/categories`
- `GET /api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/remediations`

Every new `IntentProductMatch.explanation` stores the canonical category key evaluated by the
matcher. Historical analytics therefore read only the append-only match explanation and its child
intent-run identity. They never join the current `Product` or `Category` rows, so later catalog
recategorization cannot rewrite an earlier report.

Category coverage returns stable category-key ordering, with the explicit unclassified bucket last.
Each row includes distinct intent and product counts, target count, all four deterministic
match-state counts, and confident coverage in basis points. Match-state counts always reconcile to
the target count. A missing category key is represented as `null`; it is not guessed from an intent
or current catalog record.

Remediation analytics use only `possible_match_missing_data` results. Each missing or conflicting
hard constraint field is aggregated by affected exact intent versions, persisted targets, and
products. Rows are ranked by affected intent count, affected product count, affected target count,
and field key. Intent, product, and target impact are reported in basis points against the selected
report scope. Multiple variants count as separate targets while the parent product is counted once.

Use the optional `category_bucket` query parameter to restrict remediation scope. Supply a
canonical category key or `_unclassified` for matches whose stored category key is `null`.
Pagination totals and impact denominators are derived from the same filtered immutable match set.

Incomplete suite runs return a conflict. Missing runs return a non-disclosing not-found response.
Malformed or unreconciled stored explanations fail closed instead of being omitted. This slice adds
no migration, provider call, catalog mutation, or frontend behavior.
