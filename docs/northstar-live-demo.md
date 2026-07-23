# Northstar Shopify live demonstration

This runbook turns the deterministic Catora showcase into a repeatable Shopify-backed sales demonstration.

## Canonical systems

- Shopify development store: `northstar-living-demo.myshopify.com`
- Catora app: `https://catora.codistan.org`
- Catora API: `https://api.catora.codistan.org`
- OAuth callback: `https://api.catora.codistan.org/api/v1/shopify/oauth/callback`

No Shopify credential, Catora encryption key, database URL or presenter password belongs in this repository.

## 1. Build the import package

Start the local stack, apply migrations and reset the deterministic enterprise showcase:

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
npm run demo:seed
npm run demo:package-shopify
```

The command writes:

- `northstar-shopify-demo-package/northstar-shopify-products.csv`
- `northstar-shopify-demo-package/northstar-shopify-manifest.json`

The package is valid only when the manifest reports:

- store: `northstar-living-demo.myshopify.com`
- 1,000 products
- 2,000 variants
- a SHA-256 matching the CSV bytes

## 2. Load the Shopify development store

In Shopify Admin:

1. Open **Products → Import**.
2. Upload `northstar-shopify-products.csv`.
3. Enable overwrite for matching handles when resetting an existing demo store.
4. Complete the import and wait for Shopify to finish processing.
5. Confirm 1,000 products and 2,000 active variants.

Do not substitute a merchant catalog for this store. Northstar is a synthetic, deterministic fixture designed for safe demonstrations.

## 3. Install Catora

Configure the custom-distribution app with:

- app URL `https://catora.codistan.org`
- callback URL `https://api.catora.codistan.org/api/v1/shopify/oauth/callback`
- webhook endpoint `https://api.catora.codistan.org/api/v1/shopify/webhooks`
- exact read scope `read_products`

From the Catora onboarding screen, connect `northstar-living-demo.myshopify.com`. The successful grant must create one installation, one Shopify source and one initial sync job.

## 4. Reconcile the initial sync

Before using the store in a sales meeting, verify the connection panel shows:

- healthy installation and source;
- 1,000 active products;
- 2,000 active variants;
- latest sync completed;
- latest deterministic analysis completed;
- no credential or raw webhook payload displayed.

If counts do not reconcile, do not present the live-sync path. Use the timestamped last verified Catora snapshot and correct the store outside the client call.

## 5. Controlled live-change scenario

Use the same product on every call:

**Cloudline Compact Three-Seat Sofa**

Immediately before the meeting, record its current width value in Shopify. During the live demonstration:

1. Open the product in Shopify Admin.
2. Remove or alter the width metafield.
3. Save the product.
4. Return to Catora and show the signed product-update delivery or use **Sync catalog now**.
5. Show the bounded incremental sync completing.
6. Open the changed product, its source evidence and the resulting audit/intent impact.

Catora remains read-only. Restore the product in Shopify Admin after the demonstration; do not present automated storefront write-back as implemented.

## 6. Reset before every meeting

1. Restore the deterministic Shopify CSV with overwrite enabled.
2. Wait for Shopify import completion.
3. In Catora, run the protected presenter reset for the `sales-demo` workspace.
4. Confirm preflight health for PostgreSQL, Redis, worker, object storage and report generation.
5. Run **Sync catalog now** once.
6. Reconcile 1,000 products and 2,000 variants.
7. Confirm the Cloudline sofa has the prepared starting defect state.
8. Generate the PPTX and operational CSV once before the meeting.

## 7. Presentation fallback

A Shopify outage must not stop the sales story. When live synchronization is unavailable:

- show the connection as temporarily unavailable;
- retain the timestamp of the last verified snapshot;
- continue through the prepared catalog score, product evidence, buyer-intent impact, review decision and reports;
- never simulate a successful live webhook or claim fresh data.

## Client-winning sequence

1. Prove scale: 1,000 products and 2,000 SKUs.
2. Prove connection: healthy Shopify source and verified sync timestamp.
3. Prove evidence: exact product, field and source record.
4. Prove commercial consequence: affected buyer-intent eligibility.
5. Prove governance: review, verification and append-only decision history.
6. Prove actionability: editable executive PPTX and operational CSV.
7. Close on the paid pilot: continuous monitoring of the prospect's own store, not generic consulting.
