# Catora Shopify App Home

This directory contains the iframe-based embedded App Home used by Catora's public-distribution Shopify apps.

It is intentionally independent from `apps/web`:

- `apps/web` remains the standalone Catora operator and sales-demo application;
- `apps/shopify` is the merchant-facing Shopify Admin surface;
- the existing custom-distribution Northstar app continues to use the standalone onboarding flow;
- the development and production public-distribution apps use this embedded App Home.

## Runtime contract

The App Home loads Shopify App Bridge and Polaris web components directly from Shopify's CDN. It embeds only the public Shopify API key and obtains a fresh short-lived Shopify ID token for every backend request.

The browser can call only these same-origin routes:

```text
GET  /api/v1/shopify/public/session
POST /api/v1/shopify/public/activate
GET  /api/v1/shopify/public/installation
POST /api/v1/shopify/public/installation/sync
```

Vercel proxies those routes to `https://api.catora.codistan.org`. No access token, refresh token, client secret, customer data or order data is stored in the browser.

## Local validation

```bash
npm --prefix apps/shopify run check
```

Run the static development server with:

```bash
SHOPIFY_API_KEY=<development-public-app-client-id> \
CATORA_API_ORIGIN=http://localhost:8000 \
npm --prefix apps/shopify run dev
```

The app must be opened inside Shopify Admin for App Bridge to supply an authenticated ID token.

## Vercel project

Create a separate Vercel project with:

```text
Repository: waseem99/Catora
Root directory: apps/shopify
Production branch: main
Domain: shopify.catora.codistan.org
```

Set the public, non-secret build variable:

```text
SHOPIFY_API_KEY=<client ID of the linked Shopify public app>
```

Vercel production builds fail when this value is absent. The Shopify client secret and credential-encryption key belong only on the Railway API service and must never be added to this Vercel project.

The deployment configuration provides:

- static output from `dist/`;
- a narrow proxy for `/api/v1/shopify/public/*` only;
- Shopify-compatible `frame-ancestors` policy;
- App Bridge and Polaris CDN allowances;
- no camera, microphone, geolocation or payment permissions.

## Shopify registrations

Use separate Vercel deployments or environment-specific API keys when linking:

- `Catora Shopify — Development` for Partner-owned development stores;
- `Catora Shopify — Production` for App Store review and Limited visibility publication.

Both registrations use:

```text
Application URL: https://shopify.catora.codistan.org
Redirect URL: https://shopify.catora.codistan.org/auth/callback
```

The static route fallback serves the App Home for the callback path while Shopify managed installation and App Bridge complete the embedded session.
