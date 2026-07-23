# Catora deployment readiness gate

Run this gate before creating or changing the live Vercel, Railway or Shopify configuration:

```bash
npm run deploy:validate
```

The command is static and secret-free. It validates the source-controlled contract for:

- the Vercel Next.js workspace build;
- the Railway FastAPI Dockerfile, migration owner and readiness healthcheck;
- the Railway Celery worker Dockerfile and absence of worker-owned migrations;
- the canonical Catora and API URLs;
- the standalone Shopify OAuth callback;
- `embedded = false`;
- API version `2026-07`;
- exactly `read_products` and no write scopes;
- all four required app-level webhook topics at the canonical endpoint;
- blank Shopify secret examples in `.env.example`;
- the Northstar package and hosted smoke-test commands.

CI runs the same validation on every pull request and push to `main`.

## Shopify delivery boundary

The supported live configuration uses Shopify app-level subscriptions for:

- `app/uninstalled`;
- `products/create`;
- `products/update`;
- `products/delete`.

All four must target:

```text
https://api.catora.codistan.org/api/v1/shopify/webhooks
```

Do not substitute manually created store-admin product webhooks. Those use a separate store-level signing secret, while Catora verifies app webhook deliveries with the Shopify app client secret. A configuration screenshot is not acceptance; one real `products/update` delivery must receive a `2xx` response and produce an incremental synchronization.

## Production fail-closed rules

The API now refuses to start in production when any of these conditions are unsafe:

- the frontend URL is not a clean HTTPS origin;
- CORS does not contain only HTTPS origins;
- CORS does not include the configured frontend origin;
- trusted proxy headers are disabled;
- an enabled Shopify callback is not HTTPS;
- the Shopify callback does not use `/api/v1/shopify/oauth/callback`;
- Shopify requests anything other than `read_products`;
- expiring offline Shopify tokens are disabled;
- the Shopify credential-encryption key is missing or invalid.

These checks do not print secret values.

## Hosted go/no-go gate

After deployment and seeding, run the authenticated hosted smoke test from a trusted operator machine or CI secret context:

```bash
export CATORA_SMOKE_FRONTEND_URL=https://catora.codistan.org
export CATORA_SMOKE_API_URL=https://api.catora.codistan.org
export CATORA_SMOKE_EMAIL=demo@catora.local
export CATORA_SMOKE_PASSWORD='<private presenter password>'
export CATORA_SMOKE_REPORT_PATH=/tmp/catora-hosted-acceptance.json
python scripts/smoke_hosted_demo.py
```

The gate fails unless:

- the frontend login page and API health endpoints respond correctly;
- presenter preflight reports every dependency as healthy;
- the last verified snapshot and demo overview both contain exactly 1,000 products and 2,000 variants;
- source evidence, buyer-intent impact and a reviewable recommendation are present;
- the recommendation decision route is registered;
- the PPTX is a structurally valid, editable, macro-free Office package;
- the operational CSV has the required columns plus finding and recommendation rows.

After the Shopify app is installed and the initial synchronization is complete, add:

```bash
export CATORA_SMOKE_REQUIRE_SHOPIFY=true
python scripts/smoke_hosted_demo.py
```

That stricter run also requires the canonical Northstar store, an active healthy installation, exactly `read_products`, expiring offline tokens, a completed sync, reconciled 1,000/2,000 totals and persisted sync/audit metadata. The generated JSON report contains no password, token or secret value.

## Live product-change proof

The onboarding card polls Catora every five seconds while Shopify is connected. It shows the latest persisted webhook topic, HMAC-verification status, processing status, receipt time and bounded product identifier without exposing the raw payload or signature.

Before changing the Cloudline sofa width in Shopify, start the acceptance watcher:

```bash
export CATORA_SMOKE_API_URL=https://api.catora.codistan.org
export CATORA_SMOKE_EMAIL=demo@catora.local
export CATORA_SMOKE_PASSWORD='<private presenter password>'
export CATORA_SHOPIFY_CHANGE_REPORT_PATH=/tmp/catora-shopify-change.json
npm run demo:verify-shopify-change
```

Then make and save the controlled width change. The watcher ignores old webhook deliveries and fails unless a new verified `products/update` delivery is processed, creates an incremental ingestion job and is followed by a completed sync and audit with reconciled 1,000-product and 2,000-variant totals. Restore the original width after the report passes.

## External acceptance still required

Passing the repository gate does not prove that the hosted environment exists. The release operator must still:

1. deploy the frontend to Vercel;
2. deploy the API and worker to Railway;
3. provision PostgreSQL, Redis and private object storage;
4. enter secrets directly into the provider secret stores;
5. release the matching Shopify app version;
6. install the app through Catora onboarding;
7. reconcile 1,000 products and 2,000 variants;
8. run the live product-change watcher and restore the Cloudline width;
9. run the authenticated hosted smoke test with Shopify required;
10. retain both non-secret acceptance reports and verify PPTX and CSV downloads.

Never paste client secrets, access tokens, encryption keys, database URLs, passwords or webhook signing secrets into GitHub, chat, email or WhatsApp.
