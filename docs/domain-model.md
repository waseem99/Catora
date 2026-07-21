# Canonical domain model

Catora separates external source snapshots from normalized catalog intelligence.

```mermaid
erDiagram
  ORGANIZATION ||--o{ WORKSPACE : owns
  WORKSPACE ||--o{ MEMBERSHIP : grants
  USER ||--o{ MEMBERSHIP : receives
  WORKSPACE ||--o{ CATALOG_SOURCE : configures
  CATALOG_SOURCE ||--o{ INGESTION_JOB : runs
  INGESTION_JOB ||--o{ SOURCE_RECORD : snapshots
  WORKSPACE ||--o{ PRODUCT : contains
  PRODUCT ||--o{ PRODUCT_VARIANT : has
  PRODUCT ||--o{ PRODUCT_ATTRIBUTE : describes
  SOURCE_RECORD ||--o{ EVIDENCE_REFERENCE : supports
  PRODUCT_ATTRIBUTE ||--o{ EVIDENCE_REFERENCE : cites
  RULE_DEFINITION ||--o{ RULE_VERSION : versions
  AUDIT_RUN ||--o{ AUDIT_FINDING : creates
  RULE_VERSION ||--o{ AUDIT_FINDING : produces
  BUYER_INTENT ||--o{ INTENT_RUN : executes
  INTENT_RUN ||--o{ INTENT_PRODUCT_MATCH : evaluates
  PRODUCT ||--o{ RECOMMENDATION : improves
  RECOMMENDATION ||--o{ RECOMMENDATION_FIELD : proposes
  RECOMMENDATION_FIELD ||--o{ REVIEW_DECISION : reviews
  CHANGE_SET ||--o{ CHANGE_SET_ITEM : contains
  MARKET_COMPARISON ||--o{ MARKET_CONFLICT : finds
  REPORT_JOB ||--o{ EXPORT_ARTIFACT : creates
  MEASUREMENT_BASELINE ||--o{ PRODUCT_COHORT : defines
```

## Value states

Catalog fields distinguish `missing`, `unknown`, `not_applicable`, `conflicting` and `present`. These states are not interchangeable.

## Identity

- Internal IDs are UUIDs.
- External IDs remain scoped to their source.
- SKU is searchable but never assumed globally unique.
- A product may be linked across markets while retaining market-specific copy, price, availability and URLs.

## Deletion policy

Storefronts, sources, products and variants may be soft deleted. Source records, evidence, audits, findings, recommendations, review decisions, change sets, reports and audit events remain historical until a governed retention process removes them.
