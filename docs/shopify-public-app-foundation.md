# Shopify public app foundation

This document covers the repository-controlled execution slices for epic #154.

## Distribution model

Catora will use three independent Shopify app identities:

- the existing custom-distribution Northstar pilot app;
- `Catora Shopify — Development`, a public-distribution app linked only to Partner-owned development stores before review;
- `Catora Shopify — Production`, a public-distribution app submitted for review and published with Limited visibility.

The real Shopify client IDs and secrets are provider-side values. The templates under `shopify/public/` intentionally retain `LINK_WITH_SHOPIFY_CLI` and must be linked locally with Shopify CLI.

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

## Expiring offline token exchange

After invitation activation and prospect-workspace provisioning are complete, the backend exchanges the verified session token at the shop's OAuth token endpoint using:

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token_type=urn:ietf:params:oauth:token-type:id_token
requested_token_type=urn:shopify:params:oauth:token-type:offline-access-token
expiring=1
```

Catora requires all of the following before credentials can be persisted:

- access token;
- rotating refresh token;
- positive access and refresh expiry metadata;
- exact granted scope `read_products` and no write scope.

Token bundle objects suppress credentials from their representation. The persistence/rotation wiring is the next #158 implementation slice.

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
- the existing HMAC-verified product/uninstall webhook endpoint;
- separate development and production Shopify registrations.

Public app runtime configuration is separate from the existing Northstar custom app:

```text
CATORA_SHOPIFY_PUBLIC_ENABLED
CATORA_SHOPIFY_PUBLIC_CLIENT_ID
CATORA_SHOPIFY_PUBLIC_CLIENT_SECRET
CATORA_SHOPIFY_PUBLIC_APP_URL
CATORA_SHOPIFY_PUBLIC_REQUIRED_SCOPES
CATORA_SHOPIFY_PUBLIC_HTTP_TIMEOUT_SECONDS
CATORA_SHOPIFY_PUBLIC_SESSION_CLOCK_SKEW_SECONDS
```

Run the source-controlled validation with:

```bash
python scripts/validate_shopify_public_app_contract.py
```

Compliance webhooks are intentionally not declared until issue #162 adds dedicated HMAC-validating privacy and deletion handlers. Publishing the production app before that issue is complete is prohibited.

## External setup still required

An operator with Shopify app-development access must:

1. create the two public-distribution app registrations;
2. link each template with Shopify CLI without committing the generated client ID;
3. create the `shopify.catora.codistan.org` deployment and DNS target when the embedded app shell is implemented;
4. enter the environment-specific client credentials only in the deployment provider;
5. deploy Shopify app configuration versions through Shopify CLI.

The repository can continue with prospect-workspace provisioning, encrypted public-token persistence and the embedded App Home while those registrations are being prepared.
