# Buyer-intent drafts and versions

Buyer intents use immutable content versions grouped by `lineage_id`.

- Creating an intent starts version 1 in `draft` status.
- Editing requires `expected_version` and inserts a new draft row; it never overwrites prior content.
- A stale edit or approval returns a conflict rather than silently replacing newer work.
- Approving the latest draft marks an older approved version in the same lineage as `superseded`.
- Every create, revise and approve operation emits an attributable audit event.
- Read operations are available to workspace members. Authoring and approval require `analysis.run`.
- List totals are computed from the same latest-version query used for page items.

The stored `structured_intent` is validated against the deterministic matcher contract. Natural-language
parsing, execution orchestration and coverage aggregation remain separate Issue #10 slices.
