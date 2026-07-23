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

## External acceptance still required

Passing the repository gate does not prove that the hosted environment exists. The release operator must still:

1. deploy the frontend to Vercel;
2. deploy the API and worker to Railway;
3. provision PostgreSQL, Redis and private object storage;
4. enter secrets directly into the provider secret stores;
5. release the matching Shopify app version;
6. install the app through Catora onboarding;
7. reconcile 1,000 products and 2,000 variants;
8. test a real product-update webhook and incremental analysis;
9. run the authenticated hosted smoke test;
10. verify editable PPTX and operational CSV downloads.

Never paste client secrets, access tokens, encryption keys, database URLs, passwords or webhook signing secrets into GitHub, chat, email or WhatsApp.
