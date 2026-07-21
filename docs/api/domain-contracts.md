# Domain API contracts

All future business endpoints live below `/api/v1` and require an authenticated workspace context. Workspace membership is validated server-side; callers cannot authorize themselves by supplying a workspace ID.

## Sources

`POST /api/v1/workspaces/{workspace_id}/sources`

```json
{
  "name": "UAE Shopify catalog",
  "source_type": "shopify",
  "storefront_id": null,
  "config": {"shop_domain": "example.myshopify.com"}
}
```

## Products

`GET /api/v1/workspaces/{workspace_id}/products?market=AE&severity=high`

Products expose canonical values and separate evidence links. Raw source payloads are administrative/debug resources and are not embedded by default.

## Audits and findings

`POST /api/v1/workspaces/{workspace_id}/audits` starts a versioned background run. Every finding references an immutable rule version and exact source snapshot.

## Buyer intents

`POST /api/v1/workspaces/{workspace_id}/intents`

```json
{
  "name": "Compact easy-care sofa",
  "query": "A three-seat sofa under 220 cm wide that is easy to clean",
  "market": "AE"
}
```

The parsed hard and soft constraints must be shown for user approval before an intent run.

## Recommendations and review

Recommendations are field-level. Approving one field never implicitly approves another. Approved values enter an immutable ChangeSet before export or optional future writeback.

## Reports

`POST /api/v1/workspaces/{workspace_id}/reports`

```json
{
  "report_type": "executive_catalog_assessment",
  "audit_run_id": "00000000-0000-0000-0000-000000000000",
  "intent_run_ids": [],
  "market_comparison_ids": []
}
```

Report jobs snapshot their input contract and template version so generated artifacts can be reproduced and audited.
