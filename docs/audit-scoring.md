# Deterministic audit scoring

Catora audit scores are computed entirely from versioned rule evaluations. No LLM output participates in a finding fingerprint, pass/fail decision, severity weight, denominator, score, or confidence value.

## Rule evaluation

The first engine version consumes compiled `taxonomy_field_requirement` rules. Each required or recommended field can contribute:

- a completeness check for presence;
- a consistency check for canonical type, format, range and unit validity;
- a variant-quality check when the field is variant-scoped;
- a discoverability-readiness check when the field maps to an SEO or Schema.org role;
- a market-consistency check when the rule names specific markets.

A missing variant scope is reported explicitly. Values are never coerced during audit execution. Type, unit, range, enum, URL, date, length and pattern checks operate on the normalized canonical value supplied to the engine.

## Relational consistency constraints

Immutable rule specifications may add explicit relational constraints without executing arbitrary code:

- `less_than_or_equal_to_field` compares a numeric value with another canonical field in the same product or variant scope;
- `greater_than_or_equal_to_field` performs the inverse numeric comparison;
- `matches_product_field` requires a variant-scoped value to equal the named canonical product value, including its canonical type, unit and locale.

Numeric relationships are compared only when both canonical values are present and use the same unit. A missing related value produces a `not_evaluated` contribution rather than an invented pass or failure. Incomparable values and unit mismatches produce explicit deterministic failure codes. Relationship findings use the `cross_field_consistency` check key and the `reconcile_related_values` remediation type.

The bundled furniture taxonomy remains version `1.0.0` and is unchanged by this executor capability. Relational constraints must be present in an immutable rule specification before they contribute to an audit.

## Severity weights

| Severity | Weight |
| --- | ---: |
| Critical | 100 |
| High | 60 |
| Medium | 30 |
| Low | 10 |
| Informational | 5 |

The rule version stores the severity. The engine does not infer severity from text.

## Score formula

For a dimension or the overall catalog:

```text
score_basis_points = round(10,000 × passed_weight ÷ evaluated_weight)
```

`evaluated_weight` includes passed and failed checks. Checks marked `not_evaluated` are excluded from the score denominator but remain visible in contributions.

The displayed score is `score_basis_points / 100`, producing a value from 0.00 to 100.00.

## Confidence formula

Each product snapshot supplies source coverage from 0 to 10,000 basis points. Confidence is:

```text
confidence_basis_points =
    sum(evaluation_weight × source_coverage_basis_points)
    ÷ eligible_weight
```

Only evaluated checks contribute covered weight. Low source coverage therefore lowers confidence without silently improving or reducing the pass ratio.

## Finding fingerprints

A finding fingerprint is SHA-256 over canonical JSON containing:

- rule version ID;
- product ID;
- optional variant ID;
- field key;
- check key;
- sorted deterministic failure codes.

The affected value is intentionally excluded. A changed invalid value remains the same ongoing finding; a different failure mode creates a new fingerprint. This enables later persistence code to reconcile new, ongoing, resolved and regressed findings reproducibly.

## Explainability

Every score returns its eligible, evaluated and passed weights plus the complete ordered contribution list. Each failed evaluation includes the rule version, scope, severity, field, affected value, evidence, business-impact category, remediation type and deterministic failure codes.
