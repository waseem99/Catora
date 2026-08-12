# Catora portable production deployment

This directory is the provider-neutral production/recovery contract for Catora. GitHub/GHCR are the release source of truth; Railway, Vercel and any future platform are optional hosting adapters.

Canonical production origins stay stable across provider moves:

- frontend: `https://catora.codistan.org`
- API: `https://api.catora.codistan.org`

The production deploy must promote the exact web/API/worker image digests that passed staging certification. Do not rebuild images during promotion.

## Files

- `docker-compose.production.yml` — application-only deployment for managed PostgreSQL, Redis and S3-compatible storage.
- `docker-compose.dependencies.yml` — optional PostgreSQL 17 + Redis + MinIO recovery overlay for a single Docker host.
- `.env.production.example` — variable names only. Copy it beside the compose files as a protected `.env.production`; never commit the populated file.

## Mandatory data recovery before cutover

If an existing production environment or backup is available, recover data before initializing a replacement production stack.

1. Export PostgreSQL with a consistent dump, for example:

   ```bash
   pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL" > catora-production.dump
   ```

2. Copy the object-storage bucket with an S3-compatible tool such as `rclone` or `aws s3 sync`.
3. Inventory production environment variables through a secure secret channel.
4. Preserve the encryption/signing material that matches the restored database. At minimum preserve, when used:
   - `CATORA_AUTH_TOKEN_PEPPER`
   - `CATORA_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY`
   - `CATORA_CATALOG_BRIDGE_CREDENTIAL_ENCRYPTION_KEY`
   - `CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY`
   - `CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY`
   - every credential variable referenced by an existing `env:` managed-credential record, including Google measurement credentials.
5. Treat Redis as disposable unless a specific durable requirement has been identified.

Changing an encryption key while keeping encrypted database records can make existing connector credentials unreadable. Never run demo or staging seed scripts against restored production data.

## Build/promotion evidence

Use a staging certification artifact whose `staging-certification.json` says `READY FOR UAT`. Copy the exact values into the deployment environment:

```text
CATORA_PRODUCTION_RELEASE_GIT_SHA
CATORA_PRODUCTION_RELEASE_CI_RUN_ID
CATORA_PRODUCTION_API_IMAGE_DIGEST
CATORA_PRODUCTION_WORKER_IMAGE_DIGEST
CATORA_PRODUCTION_WEB_IMAGE_DIGEST
```

The three digests must come from the same certified Git SHA/CI release. `CATORA_PRODUCTION_*_PREVIOUS_IMAGE` should point to the currently deployed digest for rollback, or `none` only for a true first/recovery deployment with no known predecessor.

## Managed dependencies mode

Use this when PostgreSQL, Redis and S3-compatible storage are supplied by the chosen hosting provider.

1. Create a protected runtime file beside the portable compose files:

   ```bash
   cp deploy/portable/.env.production.example deploy/portable/.env.production
   chmod 600 deploy/portable/.env.production
   ```

2. Populate it through the provider secret manager or another approved secret channel. Required canonical values include:

   ```text
   CATORA_ENVIRONMENT=production
   CATORA_FRONTEND_URL=https://catora.codistan.org
   CATORA_CORS_ORIGINS=["https://catora.codistan.org"]
   CATORA_TRUST_PROXY_HEADERS=true
   ```

3. Supply managed `CATORA_DATABASE_URL`, `CATORA_REDIS_URL`, and S3 variables.
4. Validate and pull exact images:

   ```bash
   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml config

   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml pull
   ```

5. Run the schema migration exactly once:

   ```bash
   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml \
     --profile ops run --rm migrate
   ```

6. Start the exact API, worker and web images:

   ```bash
   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml \
     up -d api worker web
   ```

The worker never owns migrations.

## Single-host recovery mode

This is the emergency path when no managed dependencies are available.

1. Populate the normal production environment plus:

   ```text
   CATORA_SELF_HOSTED_POSTGRES_PASSWORD
   CATORA_SELF_HOSTED_S3_ACCESS_KEY
   CATORA_SELF_HOSTED_S3_SECRET_KEY
   CATORA_SELF_HOSTED_S3_BUCKET
   ```

2. Start dependencies:

   ```bash
   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml \
     -f deploy/portable/docker-compose.dependencies.yml \
     up -d postgres redis minio
   ```

3. Initialize the MinIO bucket:

   ```bash
   docker compose --env-file deploy/portable/.env.production \
     -f deploy/portable/docker-compose.production.yml \
     -f deploy/portable/docker-compose.dependencies.yml \
     --profile ops run --rm storage-init
   ```

4. Restore the PostgreSQL dump and object-storage data before application acceptance.
5. Run migration once, then start API/worker/web using both compose files.

Persistent volumes in this mode are an emergency recovery mechanism, not a substitute for external backups.

## Pre-DNS acceptance

Before changing DNS, test the replacement host/provider directly through its temporary ingress or local reverse proxy.

Require all of the following:

- frontend `/login` returns the Catora app;
- API `/health/live` returns `status=ok`;
- API `/health/ready` returns `status=ready` with PostgreSQL, Redis and object storage healthy;
- API `/health/release`, web `/api/release` and `/health/worker` report the certified SHA and exact production digests;
- an existing production user can authenticate;
- the restored workspace/catalog data is visible;
- existing Service Visibility sources are present when the old database was restored.

## DNS cutover

1. Lower DNS TTL ahead of the window when possible.
2. Point `api.catora.codistan.org` to the replacement API ingress.
3. Confirm API live/ready/release endpoints through the canonical domain.
4. Point `catora.codistan.org` to the replacement web ingress.
5. Run authenticated production smoke through the canonical domains.
6. Keep the previous environment or backups intact until acceptance passes.

## Hilarious continuity

After the provider move, do not create a replacement Hilarious source merely to make the system look healthy. With restored production state:

1. sign in to Catora;
2. open the existing Hilarious Service Visibility source;
3. confirm source continuity;
4. verify WordPress Connection Health;
5. run one manual snapshot;
6. rotate the WordPress bridge credential only when required by the existing acceptance procedure;
7. continue the publish → automatic re-scan → finding lifecycle → measurement loop.

## Rollback

Keep the previous production image digests and database/object-storage backup until the new deployment is accepted. Roll back application containers by restoring the previous digest values and running `docker compose up -d`. Database rollback must use an explicit compatible backup/migration plan; never assume an application-image rollback automatically reverses schema changes.
