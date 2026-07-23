# Catalog onboarding and processing journey

Catora presents three authenticated entry paths inside a workspace:

1. **Explore sample catalog** opens the deterministic Northstar client demonstration.
2. **Upload Shopify CSV** creates a private, tenant-scoped source and real ingestion job.
3. **Connect Shopify** remains visibly unavailable until the private installation and encrypted credential lifecycle in #124 is complete.

## Shopify CSV diagnostic

The upload path expects Shopify's standard product export headings, including:

- `Handle`;
- `Title`;
- `Variant SKU`;
- `Body (HTML)`;
- `Variant Price`;
- `Variant Inventory Qty`;
- `Type`;
- `Image Src`.

Shopify represents one product with multiple variant rows and commonly leaves product-level cells blank after the first row. The Shopify CSV profile inherits the product identifier and title within the product group while preserving each variant SKU as the stable variant identity. Resume parsing reconstructs the same inherited state before continuing from a row checkpoint.

## Retry and resume

The browser stores only the created source ID and ingestion job ID in session storage. It never stores CSV contents, credentials, object-storage keys or source rows. A refresh or transient failure can resume the same source/job rather than creating a duplicate.

The API remains authoritative for:

- authenticated workspace membership;
- source-write permission;
- CSRF validation;
- object ownership;
- source validation;
- active-job conflict prevention;
- persisted job counts and lifecycle state.

## Processing status

The processing screen derives completed states only from persisted ingestion-job fields and the normalization checkpoint. It shows:

- uploaded;
- source validated;
- import queued/running/completed;
- processed, accepted, rejected and warning counts;
- normalization and taxonomy completion;
- failed or cancelled state;
- the last successfully loaded state during a transient refresh failure.

It does not fabricate a progress percentage. Once normalization is persisted, the route opens the workspace product catalog automatically.

Deterministic audit, buyer-intent and client-branded report stages are displayed as not started until the prospect-assessment orchestrator persists those records. This prevents the UI from implying that an analysis occurred when only import and normalization have completed.

## Follow-on delivery

- #122: persist and orchestrate audit, intent, recommendation and report stages after normalization.
- #123: create prospect-specific branded diagnostic results and forwardable artifacts.
- #124: enable the private Shopify installation path and encrypted credential lifecycle.
