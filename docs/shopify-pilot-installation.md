# Controlled Shopify pilot installation and synchronization

Catora's first merchant connection uses a custom-distribution Shopify app, not a public App Store listing. The app is a standalone integration and requests only the `read_products` Admin API scope used by the catalog connector.

## Canonical environment

- App URL: `https://catora.codistan.org`
- OAuth callback: `https://api.catora.codistan.org/api/v1/shopify/oauth/callback`
- Webhook endpoint: `https://api.catora.codistan.org/api/v1/shopify/webhooks`
- Northstar development store: `northstar-living-demo.myshopify.com`

Add the complete callback URL to the app's allowed redirection URLs in the Shopify Dev Dashboard. Use the permanent Northstar `myshopify.com` hostname above for installation, synchronization, presenter checks and reset validation.

## App configuration

`shopify.app.toml.example` is the source-controlled, non-secret app configuration template. Link a local copy to the Codistan Dev Dashboard app with Shopify CLI, then deploy its configuration. The template registers:

- API version `2026-07`;
- read-only `read_products` access;
- `app/uninstalled`;
- `products/create`;
- `products/update`;
- `products/delete`;
- the canonical Catora webhook endpoint.

Do not commit the linked app's real client ID, client secret, access tokens or encryption key.

## Required environment

Set the following on the Catora API and worker. Secrets must be entered directly in Railway or the approved secret manager.

```text
CATORA_SHOPIFY_ENABLED=true
CATORA_SHOPIFY_CLIENT_ID=<Dev Dashboard client ID>
CATORA_SHOPIFY_CLIENT_SECRET=<Dev Dashboard client secret>
CATORA_SHOPIFY_CALLBACK_URL=https://api.catora.codistan.org/api/v1/shopify/oauth/callback
CATORA_SHOPIFY_REQUIRED_SCOPES=["read_products"]
CATORA_SHOPIFY_EXPIRING_OFFLINE_TOKENS=true
CATORA_SHOPIFY_OAUTH_STATE_TTL_MINUTES=10
CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY=<URL-safe base64 of 32 random bytes>
```

Generate the encryption key in a trusted shell and store only its output in the secret manager:

```bash
python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

Never rotate this key without an explicit credential migration or merchant reconnection plan. Existing encrypted installations cannot be decrypted with a replacement key.

## Installation and initial analysis

1. An owner or admin enters `northstar-living-demo.myshopify.com` in Catora for the live demonstration, or the qualified pilot merchant's permanent `*.myshopify.com` domain.
2. Catora creates a short-lived, one-time OAuth state and sets an HTTP-only SameSite callback cookie.
3. The browser is redirected to Shopify's grant screen.
4. Catora validates the callback state, browser cookie, shop hostname and Shopify query HMAC.
5. The authorization code is exchanged for an offline token.
6. Catora validates that Shopify granted exactly `read_products`.
7. Access and refresh tokens are encrypted with AES-GCM using installation and shop identity as associated data.
8. A Shopify catalog source receives only a `shopify-installation:<uuid>` credential reference.
9. Catora queues one initial catalog synchronization automatically.
10. The worker imports and normalizes the catalog, assigns the bundled taxonomy, runs a deterministic audit and persists reconciled product, variant and warning totals.
11. The browser returns to the onboarding screen and shows connection health, synchronization status and the timestamp of the last verified analysis. No access or refresh token is returned by any API response.

## Webhook lifecycle

Catora verifies Shopify's HMAC over the exact raw request body before trusting headers or parsing JSON. Each delivery is persisted using the Shopify webhook delivery ID so retries are idempotent.

Product create and update deliveries request bounded incremental synchronization. When a synchronization is already active, repeated deliveries are coalesced behind that job and their product IDs are bounded rather than creating one full audit per webhook.

Product deletion immediately retires the matching canonical product and variants, then queues a reconciliation synchronization. No storefront mutation is performed.

`app/uninstalled` immediately:

- revokes the installation;
- clears encrypted access and refresh credentials;
- clears the source credential reference;
- disconnects the source;
- clears pending webhook work;
- cancels every queued, validating or running synchronization for that source;
- records a non-sensitive audit event.

## Manual synchronization and verified fallback

Owners and admins can press **Sync catalog now**. The same coalescing rules apply if another synchronization is active.

The onboarding screen displays:

- shop hostname and connection health;
- current sync state;
- product and variant counts;
- warning count;
- last successful sync time;
- a safe error category when the latest sync stops.

A failed refresh does not erase the previous successful counts or timestamp. The presenter can continue with the last verified snapshot while the operator resolves the live dependency.

## Expiry and reconnect

Catora requests expiring offline tokens by default. Before a connector resolves an access token, Catora refreshes credentials when the access token is within five minutes of expiry. Shopify refresh-token rotation replaces both encrypted values atomically.

When the refresh token is missing, expired, corrupt or rejected, the installation becomes `refresh_required`. The operator authorizes the shop again; Catora reuses the existing installation and source instead of duplicating them.

## Controlled disconnect

The protected disconnect action:

- clears encrypted access and refresh token material;
- clears the catalog source credential reference;
- marks the source and installation disconnected;
- records a non-sensitive audit event.

Disconnect does not delete historical immutable source evidence. Retention and organization deletion remain explicit Catora operations.

## Security boundaries

- only owner/admin users with source-management permission can initiate, synchronize or disconnect a shop;
- OAuth state records expire and cannot be replayed;
- OAuth query HMAC verification and webhook raw-body HMAC verification are separate controls;
- scopes are fail-closed and cannot expand beyond `read_products`;
- tokens are excluded from schemas, UI, logs and audit payloads;
- webhook records persist hashes and bounded identifiers rather than complete merchant payloads;
- the encryption key, client secret and tokens never belong in GitHub, WhatsApp or email;
- the app performs no storefront write-back.

## Automated acceptance

The `Shopify pilot lifecycle validation` GitHub workflow runs against PostgreSQL and proves:

- minimum-scope authorization URL construction;
- one-time state and callback verification;
- token exchange with no plaintext persistence;
- encrypted credential resolution;
- idempotent reconnect;
- automatic and manual sync queue behavior;
- burst coalescing behind one active job;
- raw-body webhook HMAC validation;
- duplicate-delivery suppression;
- uninstall credential revocation and active-job cancellation;
- credential and source-reference removal on disconnect.

## Live acceptance gate

The connected-demo release is complete only after all of these external checks pass against `northstar-living-demo.myshopify.com`:

- the Dev Dashboard app uses the canonical Codistan app, callback and webhook URLs;
- Railway contains the client ID, client secret and encryption key as secrets;
- the browser completes the real Shopify grant and returns to Catora;
- the initial sync imports the Northstar catalog and displays reconciled counts;
- one controlled product update reaches Catora through a verified webhook and incremental sync;
- a repeated webhook delivery does not create duplicate work;
- reconnect reuses the same installation and source;
- uninstall or disconnect removes active credential access;
- the timestamped last verified snapshot remains usable if Shopify is unavailable.

Until this live checklist passes, the repository implementation is validated but the external Shopify environment is not yet verified.
