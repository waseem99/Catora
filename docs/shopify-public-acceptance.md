# Shopify public app acceptance

This runbook turns the development public app into a repeatable acceptance process while preserving the existing custom-distribution app as Catora's controlled private client-demo route.

## Distribution tracks

### Controlled private client demonstrations

Use the existing custom-distribution Northstar app and standalone Catora interface:

```text
Application: existing Northstar custom-distribution app
Catora UI: https://catora.codistan.org
API: https://api.catora.codistan.org
```

Do not replace its client ID, secret, callback, encryption key, installation or Shopify configuration while validating the public app.

### Public app development and review

Use separate Shopify registrations:

```text
Catora Shopify — Development
Catora Shopify — Production
```

The development registration is linked only to Partner-owned development stores until acceptance is complete. The production registration remains unsubmitted until the full acceptance record and App Store assets are ready.

## Required external setup

Complete these steps before running authenticated acceptance:

1. Create `Catora Shopify — Development` with public distribution.
2. Link `shopify/public/shopify.app.development.toml.example` using Shopify CLI without committing the generated client ID.
3. Create a Vercel project from `waseem99/Catora` with root directory `apps/shopify`.
4. Set `SHOPIFY_API_KEY` in that Vercel project to the development public app client ID.
5. Attach `shopify.catora.codistan.org` and complete DNS/TLS validation.
6. On the Railway API service, set the development public app values:

```text
CATORA_SHOPIFY_PUBLIC_ENABLED=true
CATORA_SHOPIFY_PUBLIC_CLIENT_ID=<development public app client ID>
CATORA_SHOPIFY_PUBLIC_CLIENT_SECRET=<development public app client secret>
CATORA_SHOPIFY_PUBLIC_APP_URL=https://shopify.catora.codistan.org
CATORA_SHOPIFY_PUBLIC_REQUIRED_SCOPES=["read_products"]
CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY=<separate URL-safe Base64 32-byte key>
```

7. Deploy the API, worker, App Home and development Shopify app configuration.
8. Create an invitation for the permanent development-store `*.myshopify.com` hostname.
9. Install and open the development app from Shopify Admin.

The public client ID is not secret and belongs in the App Home build. The client secret and credential-encryption key belong only on Railway. Never paste either secret into chat, issue comments, screenshots or source control.

## Acceptance harness

The source-controlled command is:

```bash
python scripts/accept_shopify_public_app.py
```

The harness writes only sanitized metadata. It never includes the session token or app secret in its report.

### Phase 1 — deployment preflight

This phase uses no credentials and is safe to run repeatedly:

```bash
python scripts/accept_shopify_public_app.py \
  --app-url https://shopify.catora.codistan.org \
  --api-url https://api.catora.codistan.org
```

It verifies:

- App Home availability;
- linked Shopify API key rather than a development placeholder;
- official App Bridge and Polaris assets;
- Shopify-compatible frame policy;
- API dependency readiness.

### Phase 2 — authenticated store bootstrap

Open Catora inside Shopify Admin. In the browser developer console for that embedded app, obtain a fresh ID token:

```javascript
await shopify.idToken()
```

Do not paste the token into chat or save it in shell history. Run the acceptance command immediately and enter the token at the hidden prompt:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --session-token-stdin
```

This verifies the signed session, permanent shop domain, invitation status and feature tier. Shopify ID tokens are short-lived, so obtain another fresh token before a later phase when necessary.

### Phase 3 — activation and first synchronization

For a pending invitation:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --session-token-stdin \
  --activate \
  --report artifacts/shopify-public-activation.json
```

This explicitly permits the harness to:

- exchange the session token for expiring offline credentials;
- provision the isolated store workspace;
- activate the invitation;
- queue the first catalog synchronization;
- inspect the bounded installation status.

The report must contain no credential field and should show the expected shop domain, workspace, installation state and synchronization state.

After the initial job completes, run a status check with a new ID token:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --session-token-stdin \
  --report artifacts/shopify-public-status.json
```

Acceptance requires:

- installation status `active`;
- synchronization status `completed`;
- nonnegative product, variant and warning counts;
- taxonomy counts whose total matches the categorized catalog population;
- a successful synchronization timestamp;
- no reauthorization requirement.

### Phase 4 — manual synchronization

Use a fresh ID token and explicitly allow the state-changing action:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --session-token-stdin \
  --sync \
  --report artifacts/shopify-public-manual-sync.json
```

The response must be `queued`, `coalesced`, `running` or already `completed`. Confirm eventual completion from the App Home with another status run.

### Phase 5 — signed compliance and product webhooks

Enter the development public app secret at the hidden prompt. The ordinary compliance check is non-destructive and verifies `customers/data_request` handling:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --public-secret-stdin \
  --report artifacts/shopify-public-compliance.json
```

To also queue a product-update synchronization through the verified public-app webhook identity:

```bash
python scripts/accept_shopify_public_app.py \
  --shop-domain prospect-store.myshopify.com \
  --public-secret-stdin \
  --product-webhook \
  --report artifacts/shopify-public-product-webhook.json
```

The product probe is state-changing but not destructive. It must be performed only against an invited development store.

## Destructive acceptance

The harness intentionally does not automate `app/uninstalled` or `shop/redact`. Those operations revoke credentials or delete the isolated workspace and therefore require an explicit disposable-store plan.

Use a dedicated Partner-owned development store and complete both tests separately:

1. **Uninstall acceptance**
   - uninstall the public app through Shopify Admin;
   - confirm the matched public installation becomes revoked;
   - confirm its encrypted credentials are cleared;
   - confirm the catalog source is disconnected;
   - confirm the private custom-distribution installation is unchanged.

2. **Shop-redact acceptance**
   - reinstall and activate the disposable store if needed;
   - send Shopify's signed `shop/redact` delivery through the development app configuration or an approved signed operator request;
   - confirm the isolated organization/workspace and invitation are removed;
   - confirm the `workspaces/{workspace_id}/` object-storage prefix is empty;
   - confirm only the sanitized compliance receipt remains in the issuer workspace.

Never run either destructive test against Northstar or a client store.

## Reauthorization acceptance

To test rotating offline credentials:

1. Activate the development store and confirm a successful sync.
2. Reopen the embedded app and activate again with a fresh Shopify ID token.
3. Confirm the same Catora workspace, storefront, installation and catalog source are reused.
4. Confirm the refresh token is rotated and the API still returns no credential material.
5. Run another synchronization and confirm completion.

## Final development acceptance record

Store sanitized reports under `artifacts/` or another private operator location. The final development record must show:

- deployment preflight passed;
- invitation gating passed;
- first activation passed;
- initial and manual synchronization passed;
- product webhook routing passed;
- customer privacy request passed;
- reauthorization passed;
- uninstall passed on a disposable store;
- shop-redact passed on a disposable store;
- Northstar private-demo validation remained green throughout.

Only after that record exists should the production registration be linked, configured with production-only secrets, tested on an approved review store and submitted to Shopify App Review.
