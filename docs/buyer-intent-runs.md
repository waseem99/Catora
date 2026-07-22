# Deterministic buyer-intent runs

An intent run evaluates one explicitly approved buyer-intent version against the current
canonical catalog snapshot.

- Only active, non-deleted products are eligible.
- A product without active variants creates one product-level target.
- A product with active variants creates one target per variant.
- Product-level canonical facts are inherited by variants; variant facts override matching keys.
- Canonical values use `ProductAttribute.key`, `value`, `unit`, and `value_state` directly.
- Every confident factual constraint requires stored source evidence.
- Category keys are resolved through the product's tenant-scoped primary category.
- Duplicate canonical attributes for one product/variant/key fail closed.
- The run stores a deterministic SHA-256 snapshot hash covering the approved intent and every
  evaluated product, variant, category, fact, value state, unit, and evidence reference.
- Product-level results store the complete deterministic constraint explanation.
- Run and filtered match totals are derived from the same persisted match rows.

Creating a run requires `analysis.run`. Reads require workspace membership. Runs and matches are
append-only in this slice; rerunning creates a new immutable snapshot and result set.

This slice does not parse natural language, aggregate saved suites, or expose frontend behavior.
