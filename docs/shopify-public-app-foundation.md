# Shopify public app foundation

This document covers the repository-controlled execution slices for epic #154.

## Distribution model

Catora uses three independent Shopify app identities:

- the existing custom-distribution Northstar pilot app for controlled private client demonstrations;
- `Catora Shopify — Development`, a public-distribution app linked only to Partner-owned development stores before review;
- `Catora Shopify — Production`, a public-distribution app submitted for review and published with Limited visibility.

The custom-distribution app and public-distribution apps have separate client identities and credentials. The real Shopify client IDs and secrets are provider-side values. The templates under `shopify/public/` intentionally retain `LINK_WITH_SHOPIFY_CLI` and must be linked locally with Shopify CLI.

## Public beta invitation boundary

Limited visibility is not an authorization boundary. Catora therefore maintains one durable invitation record per permanent `*.myshopify.com` store.

An owner or admin creates an invitation through:

```text
POST /api/v1/workspaces/{workspace_id}/shopify/public-invitations
```

The invitation contains only bounded commercial metadata:

- permanent Shopify store domain;
- prospect name;
- demo feature tier;
- expiry and lifecycle state;
- issuer and activated workspace identities.

No access token, refresh token, Shopify client secret or raw catalog data is stored in the invitation.

Activation is one-time and binds the shop to one Catora workspace. Repeated activation for the same workspace is idempotent. Cross-workspace activation fails closed.

## Embedded session authentication

Every protected request from the embedded Shopify App Home uses a fresh Shopify App Bridge session token in the HTTP `Authorization: Bearer` header.

Catora verifies the token before looking up invitation or merchant data:

- JWT header is exactly `HS256` and `JWT`;
- signature is verified with the public app client secret;
- audience matches the public app client ID;
- `dest` is a permanent HTTPS `*.myshopify.com` origin;
- `iss` is the same shop's `/admin` origin;
- `iat`, `nbf` and `exp` are internally consistent and within the bounded clock skew;
- `sub`, `jti` and `sid` are present.

The authenticated bootstrap endpoint is:

```text
GET /api/v1/shopify/public/session
Authorization: Bearer <fresh Shopify session token>
```

The endpoint returns only shop, user, invitation, feature-tier, activated-workspace and expiry metadata. It never returns the bearer token, app secret, offline access token or refresh token.

An uninvited, expired or revoked store receives no activation or catalog processing.

## Store activation and first synchronization

The embedded app activates an invited store through:

```text
POST /api/v1/shopify/public/activate
Authorization: Bearer <fresh Shopify session token>
```

The activation workflow:

1. verifies the Shopify session token and permanent shop domain;
2. rechecks and locks the store invitation;
3. exchanges the session token for an expiring offline credential bundle;
4. creates an isolated organization, workspace, locale, storefront and initial market on first activation;
5. creates or reauthorizes the public Shopify installation;
6. creates or repairs the Shopify catalog source;
7. encrypts the access token and rotating refresh token with the public-app-specific AES-GCM key;
8. binds the invitation to the new workspace;
9. queues the first Shopify catalog synchronization.

The response includes only workspace, installation, catalog-source, ingestion-job and synchronization metadata. Credential values are never returned.

Reauthorization for the same invited store reuses the existing workspace, storefront, installation and catalog source. A store cannot be activated into a different workspace.

The first public synchronization uses the invitation issuer as its bounded Catora audit actor. This keeps the existing catalog audit pipeline accountable without creating a synthetic Shopify merchant password or granting the merchant access to unrelated Catora workspaces.

## Expiring offline credentials

The backend exchanges a verified session token at the shop's OAuth token endpoint using:

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token_type=urn:ietf:params:oauth:token-type:id_token
requested_token_type=urn:shopify:params:oauth:token-type:offline-access-token
expiring=1
```

Catora requires all of the following before credentials are persisted:

- access token;
- rotating refresh token;
- positive access and refresh expiry metadata;
- exact granted scope `read_products` and no write scope.

Public access and refresh tokens use the separate credential reference scheme:

```text
shopify-public-installation:<installation UUID>
```

The ingestion connector resolves that reference through `ShopifyPublicInstallationService`. Credentials are refreshed before expiry with the public app client identity, and Shopify must rotate the refresh token. A missing, expired or unrotated refresh credential puts the installation into `refresh_required` rather than falling back to the custom app identity.

## Webhook app-identity routing

The custom-distribution and public-distribution apps may use the same receiver:

```text
POST /api/v1/shopify/webhooks
```

The receiver can run with the custom app, the public app or both enabled. A delivery is accepted only when:

1. its HMAC matches exactly one configured Shopify app secret;
2. the permanent shop domain has exactly one active or refresh-required installation for that verified distribution;
3. a repeated Shopify delivery ID resolves to the same distribution as the original delivery.

Legacy installations without a distribution marker are treated as custom-distribution installations. Public installations carry `distribution=public` and cannot be targeted by a signature from the custom app, or vice versa.

If both app secrets are accidentally identical, both signatures validate and the delivery is rejected as ambiguous. Catora does not guess which app sent it.

The delivery record stores only bounded metadata, including the verified distribution, topic, shop domain, installation ID, event IDs, timestamps, product ID and a SHA-256 payload digest. The raw request body and HMAC signature are not persisted.

Product lifecycle and uninstall processing remain shared after identity verification. An uninstall revokes the matched installation, clears its encrypted credentials, disconnects the source and cancels active synchronization jobs without affecting the other app identity.

## Mandatory privacy and deletion webhooks

Both public app templates declare Shopify's mandatory compliance topics:

```text
customers/data_request
customers/redact
shop/redact
```

They are delivered to:

```text
POST /api/v1/shopify/compliance
```

The endpoint verifies the raw request body using only the public-distribution app secret. It never persists the HMAC, raw payload, customer identifiers, order identifiers or cleartext shop domain.

Catora requests only `read_products` and does not ingest Shopify customers or orders. Therefore valid `customers/data_request` and `customers/redact` deliveries are acknowledged as `no_customer_data_held`. Valid signed review probes for an unknown shop are also acknowledged without creating a database record because Catora has no data for that shop.

For a known activated store, `shop/redact` queues deletion of:

- the isolated Shopify prospect organization and workspace;
- all workspace-scoped database records through foreign-key cascades;
- the store invitation;
- every object under `workspaces/{workspace_id}/` in object storage.

Object deletion is paginated and rejects an empty prefix so the bucket cannot be deleted accidentally. After deletion, Catora retains only a sanitized receipt in the invitation issuer workspace containing the topic, action, hashes, timestamps and deleted-object count. Target workspace and organization identifiers are cleared from the completed receipt.

## Operator API

Create or reissue an invitation:

```text
POST /api/v1/workspaces/{workspace_id}/shopify/public-invitations
```

Example request:

```json
{
  "shop_domain": "prospect-store.myshopify.com",
  "prospect_name": "Prospect Store",
  "expires_in_hours": 168,
  "feature_tier": "demo"
}
```

List invitations issued by a workspace:

```text
GET /api/v1/workspaces/{workspace_id}/shopify/public-invitations
```

Revoke an invitation:

```text
DELETE /api/v1/workspaces/{workspace_id}/shopify/public-invitations/{invitation_id}
```

All operator routes require an authenticated workspace membership with catalog-source management permission. Writes also use the existing CSRF boundary.

## Shopify configuration contract

Both public app templates require:

- embedded App Home;
- Shopify managed installation rather than the legacy install flow;
- exact initial scope `read_products`;
- Admin API version `2026-07`;
- product and uninstall webhooks;
- mandatory compliance webhooks;
- separate development and production Shopify registrations.

Public app runtime configuration is separate from the existing custom-distribution app:

```text
CATORA_SHOPIFY_PUBLIC_ENABLED
CATORA_SHOPIFY_PUBLIC_CLIENT_ID
CATORA_SHOPIFY_PUBLIC_CLIENT_SECRET
CATORA_SHOPIFY_PUBLIC_APP_URL
CATORA_SHOPIFY_PUBLIC_REQUIRED_SCOPES
CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY
CATORA_SHOPIFY_PUBLIC_HTTP_TIMEOUT_SECONDS
CATORA_SHOPIFY_PUBLIC_SESSION_CLOCK_SKEW_SECONDS
```

`CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY` must be a URL-safe Base64 encoding of exactly 32 random bytes and must not reuse the custom-distribution app encryption key.

Run the source-controlled validation with:

```bash
python scripts/validate_shopify_public_app_contract.py
```

## Remaining publication blockers

The production public app must not be submitted for Shopify review until all remaining blockers are complete:

1. implement and deploy the embedded App Home at `shopify.catora.codistan.org`;
2. complete installation, reauthorization, product-webhook, uninstall and data-deletion acceptance tests on development stores;
3. prepare listing, review credentials, privacy policy, support details and reviewer instructions.

## External setup still required

An operator with Shopify app-development access must:

1. create the two public-distribution app registrations;
2. link each template with Shopify CLI without committing the generated client ID;
3. create the `shopify.catora.codistan.org` deployment and DNS target for the embedded App Home;
4. enter the environment-specific client credentials and public encryption key only in the deployment provider;
5. deploy Shopify app configuration versions through Shopify CLI.

The existing custom-distribution app remains available for controlled client demonstrations while the development public app moves through end-to-end testing and the production public app moves toward review.
