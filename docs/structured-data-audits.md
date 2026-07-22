# Deterministic structured-data evidence audits

Catora creates an immutable `builtin.<category>.<field>.structured_data_coverage` rule for every required or recommended immutable taxonomy field that declares a non-empty `mapping.schema_org_property`.

The `structured-data-coverage-v1` algorithm evaluates only present canonical values. Missing values remain the responsibility of the existing presence rules and produce a `not_evaluated` structured-data contribution rather than a duplicate finding.

A present value passes when at least one immutable evidence reference has a path segment identifying structured data, JSON-LD or Schema.org, including normalized forms such as `structured`, `jsonld`, `json_ld` or `schema_org`. Evidence from ordinary descriptions or specifications does not count as structured-data coverage.

A present value without accepted structured evidence creates one stable `structured_data_evidence_missing` finding. The contribution belongs to discoverability readiness, carries `discoverability` business impact and uses the `add_structured_data_mapping` remediation type. The original field evidence remains attached to the finding so reviewers can see where the current canonical value came from.

Rules preserve the taxonomy field's requirement, product, variant or both scope, data type, unit, allowed values, market metadata and Schema.org mapping. Optional and not-applicable fields do not create structured-data score denominators. They use the existing immutable rule-version set, so the first introduction of these rules requires a full audit baseline; later incremental runs require the same unchanged rule-version set.

This rule family verifies evidence coverage only. It does not render storefront HTML, fetch live pages, parse remote JSON-LD or claim that emitted structured data is syntactically valid. Those checks remain separate future rule versions.
