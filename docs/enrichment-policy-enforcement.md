# Enrichment policy enforcement

Synchronous recommendation generation and queued recommendation jobs resolve workspace enrichment
policy before any provider invocation.

The effective request keeps the workspace tone, unions banned claims, required terms and locked
fields, applies the lowest maximum length per field, and uses the lowest applicable run budget.
Request-level controls may add restrictions or lower limits, but cannot weaken workspace policy.

Queued jobs persist the effective, redacted request and effective budget. Workers resolve policy
again at execution time, so policy tightening after queueing is enforced while the queued snapshot
continues to prevent later weakening.

The effective request is the request sent to the provider and the request used for append-only
recommendation persistence and source-snapshot hashing.
