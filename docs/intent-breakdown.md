# Per-intent buyer-intent coverage analytics

A completed saved intent-suite run exposes:

`GET /api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/intents`

The response contains one row per immutable suite member in member-position order. Each row
identifies the exact pinned buyer-intent row, lineage and version, its stored name and source label,
structured category keys, the corresponding child intent run, its source snapshot hash, and
deterministic match totals.

The source label remains `template`, `user_entered`, or `ai_assisted`. This allows dashboard and
report clients to distinguish curated, direct-user and model-assisted interpretations without
implying that a model computed eligibility or coverage.

Per-intent counts are derived from persisted child `IntentProductMatch` rows. Target count treats
product variants independently, product count is distinct, all four state counts reconcile to the
target count, and confident coverage uses integer basis points. An empty catalog still returns every
suite member with zero targets, zero products and zero coverage.

When a suite run links to a previous completed run, each current child run is compared with the
child run for the same exact `buyer_intent_id`. Comparisons never advance to a newer lineage
version. The response includes signed target, product, state-count and confident-coverage deltas.
The first suite run returns no deltas.

The service fails closed when suite-member positions are not contiguous, members or child runs are
missing or duplicated, a child run is incomplete, a match references the wrong intent, or stored
structured intent data is invalid. It uses only immutable suite, buyer-intent, child-run and
persisted match data. No migration, provider call, catalog mutation, or frontend behavior is
introduced.
