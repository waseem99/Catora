# Shopify public app foundation

This document covers the first repository-controlled execution slice for epic #154.

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

The public embedded app will later authenticate the Shopify session token, extract the permanent shop domain and call `ShopifyInvitationService.require_activatable`. A store without an active invitation receives no Catora workspace and no catalog processing.

Activation is one-time and binds the shop to one Catora workspace. Repeated activation for the same workspace is idempotent. Cross-workspace activation fails closed.

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

The repository can continue with invitation enforcement, public token exchange and the embedded app shell while those registrations are being prepared.
