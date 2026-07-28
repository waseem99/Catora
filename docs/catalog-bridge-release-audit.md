# Catalog bridge release audit

This document records the repository-controlled release boundary for the custom Node.js/MongoDB catalog bridge.

## Repository release gates

The release is ready for a controlled production pilot when all of the following are true:

- `main` contains migration `0018_catalog_bridge_source` and the catalog bridge API routes;
- the dedicated contract workflow passes lint, strict TypeScript, tests, build, package creation, clean-project installation, migration, Ruff, strict MyPy, API tests and the root workspace build;
- the installable `@catora/catalog-bridge` package is retained as a GitHub Actions artifact for 90 days;
- `.env.example` documents the bridge enable flag, credential-encryption key, clock-skew limit and maximum batch size with safe defaults;
- `scripts/validate_catalog_bridge_release.py` passes;
- Railway API and worker deploy successfully from the same merged commit.

## External activation boundary

The repository does not contain production secrets or client-specific source credentials. Before the first project sends a snapshot, an operator must:

1. set `CATORA_CATALOG_BRIDGE_ENABLED=true` on the production API and worker;
2. set the same URL-safe base64 32-byte `CATORA_CATALOG_BRIDGE_CREDENTIAL_ENCRYPTION_KEY` on both services;
3. redeploy both services;
4. create a dedicated Catalog Bridge source in the intended Catora workspace;
5. deliver the endpoint, source ID and one-time token through an approved secret channel;
6. run the project-side dry-run before the first snapshot.

## Pilot acceptance boundary

The first production project remains tracked in issue #190. Acceptance requires source/accepted/normalized counts to reconcile, the analysis and report workflow to complete, the same snapshot to be idempotent, and a small approved catalog correction to produce traceable before/after evidence.

No direct MongoDB access, source write-back, customer/order/payment data or real-time synchronization is part of the first release.
