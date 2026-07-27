# Shopify public operational controls

This document covers the release-blocking controls that distinguish Shopify registrations and pause new invite-only activations without disrupting existing stores.

## Runtime settings

Set these values explicitly in each API and worker environment:

| Runtime | Registration identity |
| --- | --- |
| Development and test | `CATORA_SHOPIFY_PUBLIC_REGISTRATION_IDENTITY=public_development` |
| Production | `CATORA_SHOPIFY_PUBLIC_REGISTRATION_IDENTITY=public_production` |

`CATORA_SHOPIFY_PUBLIC_NEW_ACTIVATIONS_ENABLED` controls only first-time public-app activation. The API service owns enforcement; keep the same documented value on the worker so environment configuration remains auditable.

- `true`: invited stores may create their isolated Catora workspace and begin the first sync.
- `false`: first-time activation returns a temporary-unavailability response before Shopify offline-token exchange.

The pause does not disable existing installation authentication, reauthorization, synchronization, report downloads, compliance webhooks, uninstall handling, or store-data deletion.

`CATORA_SHOPIFY_PUBLIC_ENABLED` remains the broader application configuration switch and must not be used as the routine public-beta pause.

## Provenance contract

Catora records the following bounded, non-secret values on installation snapshots, catalog-source configuration, synchronization checkpoints, and audit events:

- `registration_identity`: `northstar_custom`, `public_development`, or `public_production`;
- `runtime_environment`: `development`, `test`, or `production`.

Legacy installations receive inferred provenance the next time a synchronization request is queued. If a request coalesces into an active legacy job, that active job checkpoint is also labeled.

## Incident procedure

To stop new public-beta activations:

1. Set `CATORA_SHOPIFY_PUBLIC_NEW_ACTIVATIONS_ENABLED=false` on the API service and mirror the value on the worker configuration.
2. Redeploy or restart the API according to the hosting platform procedure.
3. Confirm a pending invited store receives the temporary pause message.
4. Confirm an existing store can still open App Home, synchronize, download reports, reauthorize, uninstall, and invoke compliance handling.
5. Keep the public registration, webhooks, API, and worker available unless the incident requires the broader application switch.

To resume activation, set the flag to `true`, redeploy the API, and complete one disposable-store activation acceptance run.

Never place Shopify client secrets, offline tokens, refresh tokens, webhook signatures, or credential-encryption keys in incident tickets, chat messages, screenshots, or diagnostic exports.
