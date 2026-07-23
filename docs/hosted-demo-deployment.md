# Hosted Catora demo deployment

This is the reference deployment for the private client-winning demonstration tracked in #119.
It keeps the application architecture provider-neutral while documenting one fast hosted path:

- Vercel: Next.js frontend
- Railway: FastAPI service, Celery worker, PostgreSQL, Redis and S3-compatible bucket
- Domains: `catora.codistan.org` and `api.catora.codistan.org`

The sibling HTTPS domains are intentional. Catora uses secure `SameSite=Lax` session and CSRF
cookies in production, so the frontend and API remain under the same registrable company domain,
`codistan.org`.

## 1. Prerequisites

The operator needs:

- access to the `waseem99/Catora` GitHub repository;
- a Vercel team/project;
- a Railway project;
- DNS access for `codistan.org`;
- a production-safe demo password;
- a production authentication pepper of at least 32 random characters.

Create the provider-directed DNS records for these exact labels:

- `catora` → the Vercel frontend project;
- `api.catora` → the Railway API service.

Never commit environment values, Shopify credentials or generated demo passwords.

## 2. Railway project

Create these resources in one Railway project and one region:

1. PostgreSQL
2. Redis
3. private S3-compatible bucket
4. `catora-api` service from the GitHub repository
5. `catora-worker` service from the same repository

### API service

Keep the repository root as `/` and set the custom config file to:

```text
/deploy/railway/api.railway.json
```

The config selects `apps/api/Dockerfile`, runs `alembic upgrade head` before deployment,
checks `/health/ready`, and restarts the service on failure.

### Worker service

Keep the repository root as `/` and set the custom config file to:

```text
/deploy/railway/worker.railway.json
```

The config selects `apps/worker/Dockerfile`. It intentionally does not run migrations because
only the API release step owns schema migration.

### Shared backend variables

Set these on both API and worker unless noted otherwise:

```text
CATORA_ENVIRONMENT=production
CATORA_LOG_LEVEL=INFO
CATORA_DATABASE_URL=<Railway PostgreSQL asyncpg URL>
CATORA_REDIS_URL=<Railway Redis URL>
CATORA_S3_ENDPOINT_URL=<Railway bucket endpoint>
CATORA_S3_ACCESS_KEY=<Railway bucket access key>
CATORA_S3_SECRET_KEY=<Railway bucket secret key>
CATORA_S3_BUCKET=<Railway bucket name>
CATORA_AUTH_TOKEN_PEPPER=<at least 32 random characters>
CATORA_FRONTEND_URL=https://catora.codistan.org
CATORA_CORS_ORIGINS=["https://catora.codistan.org"]
CATORA_TRUST_PROXY_HEADERS=true
CATORA_ENRICHMENT_PROVIDER=disabled
```

Set these on the API service only:

```text
CATORA_DEMO_PASSWORD=<stable private presenter password>
CATORA_SMTP_HOST=<production SMTP host or approved test relay>
CATORA_SMTP_PORT=<SMTP port>
CATORA_SMTP_FROM=Catora <no-reply@catora.codistan.org>
```

The first private demonstration can keep enrichment disabled because the seeded recommendation
and every displayed metric are deterministic and persisted. Do not enable the mock provider in
production.

### Database URL

Catora requires SQLAlchemy's async PostgreSQL URL shape:

```text
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE
```

If Railway supplies a `postgresql://` URL, create a referenced variable that replaces the prefix
with `postgresql+asyncpg://` without exposing the password in documentation or source control.

### Object storage

Create the bucket before deploying the API. Confirm that the credentials support:

- list bucket;
- put object;
- get object;
- delete object;
- multipart upload for larger catalog files.

The API readiness endpoint checks object-storage access. Keep the bucket private and serve
uploads or exports through the API or time-limited presigned URLs.

## 3. API domain

Attach `api.catora.codistan.org` to the Railway API service and create the DNS record shown by
Railway. Wait for HTTPS issuance, then verify:

```bash
curl --fail https://api.catora.codistan.org/health/live
curl --fail https://api.catora.codistan.org/health/ready
```

Do not attach a public domain to the worker.

## 4. Vercel project

Import the GitHub repository into Vercel and configure:

```text
Root Directory: apps/web
Framework: Next.js
Production Branch: main
```

Keep **Include source files outside of the Root Directory** enabled because the web application
uses workspace packages from `/packages`. The committed `apps/web/vercel.json` installs from the
repository root and builds only `@catora/web`.

Set the production environment variable:

```text
NEXT_PUBLIC_CATORA_API_URL=https://api.catora.codistan.org
```

Attach `catora.codistan.org` and create the DNS record shown by Vercel. Do not use an unrelated
`vercel.app` hostname for the final presenter login because that changes browser cookie-site
behavior.

## 5. Seed the private demonstration

After the first healthy API deployment, run the seed command in the API service environment:

```bash
python scripts/seed_enterprise_demo.py
```

Use Railway's service shell or CLI command execution so the script receives production database
variables. The command recreates only the dedicated `sales-demo` workspace.

The login is:

```text
demo@catora.local
```

The password is the configured `CATORA_DEMO_PASSWORD`.

## 6. Authenticated go/no-go test

Run from a trusted operator machine or CI secret context:

```bash
export CATORA_SMOKE_FRONTEND_URL=https://catora.codistan.org
export CATORA_SMOKE_API_URL=https://api.catora.codistan.org
export CATORA_SMOKE_EMAIL=demo@catora.local
export CATORA_SMOKE_PASSWORD='<private presenter password>'
export CATORA_SMOKE_REPORT_PATH=/tmp/catora-hosted-acceptance.json
python scripts/smoke_hosted_demo.py
```

The test fails unless it verifies:

- the frontend login page;
- API liveness and dependency readiness;
- authenticated demo workspace membership;
- presenter preflight with every component healthy;
- a verified snapshot and demo overview with exactly 1,000 products and 2,000 variants;
- source evidence, buyer-intent impact and a reviewable recommendation;
- recommendation decision route registration;
- a structurally valid, editable, macro-free PPTX;
- an operational CSV with the required columns and actionable finding/recommendation rows.

After Shopify installation and the initial catalog synchronization, run the strict connected gate:

```bash
export CATORA_SMOKE_REQUIRE_SHOPIFY=true
python scripts/smoke_hosted_demo.py
```

That run additionally requires the canonical Northstar shop, an active healthy installation,
exactly `read_products`, expiring offline tokens, a completed sync, 1,000/2,000 reconciled totals
and persisted sync/audit metadata.

The test is read-only and does not consume the prepared recommendation decision state. Its JSON
report contains no password, token or secret value.

## 7. Live-change acceptance

Before changing the prepared Cloudline sofa width in Shopify, run:

```bash
export CATORA_SMOKE_API_URL=https://api.catora.codistan.org
export CATORA_SMOKE_EMAIL=demo@catora.local
export CATORA_SMOKE_PASSWORD='<private presenter password>'
export CATORA_SHOPIFY_CHANGE_REPORT_PATH=/tmp/catora-shopify-change.json
npm run demo:verify-shopify-change
```

Then change and save the width in Shopify. The watcher ignores older deliveries and passes only
after Catora persists a new HMAC-verified `products/update` webhook, processes it, queues bounded
incremental ingestion and completes a follow-up synchronization and audit with 1,000 products and
2,000 variants. Restore the original width after the report passes.

The onboarding card displays the latest safe webhook proof without exposing raw payloads,
signatures or credentials.

## 8. Backups and recovery

Before using client data:

- enable daily PostgreSQL backups;
- document the Railway backup retention available on the selected plan;
- export one encrypted database backup before major migrations;
- test restoring into a separate non-production project;
- retain original prospect uploads only for the agreed diagnostic window;
- keep generated reports in the private bucket;
- record the last successful smoke test and demo reset.

Railway buckets do not currently provide object versioning or lifecycle rules. Until a different
S3 provider is selected, deletion and retention must be enforced by Catora/operator procedures.

## 9. Rollback

If a deployment fails:

1. Keep the previous Railway deployment active.
2. Inspect `/health/ready` dependency results.
3. Roll back the API image before changing database state manually.
4. Use the documented Alembic downgrade only after confirming the target revision is reversible.
5. Roll back the Vercel deployment independently if the frontend fails.
6. Run the authenticated smoke test again.

Never restore a database over the active production database without first testing the backup in
a separate environment.

## 10. External monitoring

Railway's deployment health check is not continuous monitoring. Configure an external uptime
monitor for:

```text
https://api.catora.codistan.org/health/live
https://api.catora.codistan.org/health/ready
https://catora.codistan.org/login
```

Alert on sustained failures, not a single transient request. Keep operational diagnostics free of
catalog rows, tokens and other secrets.
