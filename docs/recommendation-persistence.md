# Append-only recommendation persistence

Validated enrichment results are persisted as new `Recommendation` and `RecommendationField` rows. The service does not query for an existing record, update a previous version or upsert by product and field. Re-running an unchanged request therefore creates a distinct recommendation version with the same deterministic source snapshot hash.

The source snapshot hash covers workspace, product, variant, task, allowed fields, original values, brand controls and every source identity, path, content digest, checksum and evidence kind. It changes when source content changes while remaining stable across equivalent request objects.

Recommendation execution metadata stores the gateway request identifier, prompt fingerprint, attempt count and token usage. Provider/model identity, prompt version, cost and source hash remain first-class columns. Field proposal metadata stores the explanation, claim type, inference flag and evidence-conflict flag alongside the existing original, proposed and edited values, source evidence, confidence and verification requirement.

Persistence validates workspace, product, variant and task identity between the original request and gateway result before adding any database objects. Identity mismatches fail closed and create no partial recommendation.

This slice does not expose an HTTP API or execute a provider. Product/finding selection, background orchestration, reviewer workflows and provider-specific adapters remain separate validated slices.
