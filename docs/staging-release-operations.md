# Immutable staging release operations

This document operationalizes the release-quality control in #253 together with #252, #254, #255 and #256.

## Permanent release chain

```text
PR / code
→ existing unit, build and security CI
→ Immutable release images
→ exact GHCR digests
→ Deploy and certify private staging
→ runtime revision proof
→ staging certification
→ READY FOR UAT
→ Record human UAT decision
→ explicit future production promotion approval
```

Neither staging certification nor human UAT automatically deploys production.

## 1. Immutable OCI release

`.github/workflows/release-images.yml` publishes three independent OCI images from the **same exact Git SHA**:

```text
ghcr.io/waseem99/catora-api:sha-<40-char-sha>
ghcr.io/waseem99/catora-worker:sha-<40-char-sha>
ghcr.io/waseem99/catora-web:sha-<40-char-sha>
```

Each image receives OCI revision/source labels and the GitHub Actions build run ID. The workflow records each immutable `sha256:` digest and assembles `catora-release-manifest.json`.

The digest, not the mutable tag, is the deployment authority.

No production/staging secret is passed to the Docker build.

### Runtime-portable web image

Browser API traffic is routed through the same-origin Next.js runtime proxy at `/api/backend/...`. The web container resolves its internal API origin from `CATORA_API_URL` at runtime.

This removes the previous need to rebuild the browser bundle merely to change `NEXT_PUBLIC_CATORA_API_URL`. The same immutable web image can therefore be tested in staging and later promoted to another environment with a different runtime API origin.

## 2. Private staging host

The reference staging deployment is `deploy/portable/docker-compose.staging.yml`.

It can run on a dedicated Linux VM/VPS or any Docker host. It includes:

- exact digest-addressed Catora web/API/worker images;
- PostgreSQL 17;
- Redis 8;
- MinIO staging object storage;
- Mailpit staging-only SMTP capture;
- one-shot schema migration service;
- one-shot object-storage initialization;
- one-shot deterministic enterprise demo seed;
- one-shot staging RBAC seed.

Web/API bind to `127.0.0.1` by default. Put a TLS reverse proxy/private ingress in front of them or keep access inside a VPN/private network. Do not expose staging merely to make Playwright work.

## 3. Self-hosted GitHub runner

Install a GitHub Actions runner on the staging host or on a private runner with Docker access to that host.

Set the protected `staging` GitHub Environment variable:

```text
CATORA_STAGING_DEPLOY_RUNNER_LABEL=<runner label>
```

The runner must have:

- Docker Engine;
- Docker Compose v2;
- `curl`;
- network access to the configured staging URLs;
- a sufficiently current GitHub Actions runner for the action versions used by the workflows.

The deploy workflow defaults to `self-hosted`, but a dedicated label is strongly preferred so unrelated self-hosted machines cannot receive the staging job.

## 4. GitHub `staging` environment

Configure these non-secret environment variables:

```text
CATORA_STAGING_WEB_URL=https://<private-or-allowlisted-staging-web-origin>
CATORA_STAGING_API_URL=https://<private-or-allowlisted-staging-api-origin>
CATORA_STAGING_DEPLOY_RUNNER_LABEL=<dedicated-runner-label>
CATORA_STAGING_RUNNER_LABEL=<browser-certification-runner-label>
CATORA_STAGING_WEB_BIND=127.0.0.1
CATORA_STAGING_API_BIND=127.0.0.1
CATORA_STAGING_REQUIRE_SHOPIFY=false
```

If browser certification runs on the same private self-hosted runner, `CATORA_STAGING_RUNNER_LABEL` can be the same label.

### Staging-only infrastructure secrets

Create protected/masked GitHub Environment secrets:

```text
CATORA_STAGING_POSTGRES_PASSWORD
CATORA_STAGING_S3_SECRET_KEY
CATORA_STAGING_AUTH_TOKEN_PEPPER
CATORA_STAGING_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY
CATORA_STAGING_DEMO_PASSWORD
```

Use URL-safe random material for the PostgreSQL password because the portable Compose stack interpolates it into the internal async PostgreSQL URL.

The Service Visibility encryption key must be URL-safe base64 encoding of exactly 32 random bytes, matching Catora's existing validation contract.

### Staging-only role secrets

Also configure:

```text
CATORA_STAGING_OWNER_EMAIL
CATORA_STAGING_OWNER_PASSWORD
CATORA_STAGING_ADMIN_EMAIL
CATORA_STAGING_ADMIN_PASSWORD
CATORA_STAGING_ANALYST_EMAIL
CATORA_STAGING_ANALYST_PASSWORD
CATORA_STAGING_REVIEWER_EMAIL
CATORA_STAGING_REVIEWER_PASSWORD
CATORA_STAGING_VIEWER_EMAIL
CATORA_STAGING_VIEWER_PASSWORD
CATORA_STAGING_NO_MEMBERSHIP_EMAIL
CATORA_STAGING_NO_MEMBERSHIP_PASSWORD
```

Every staging QA email must be distinct and end in:

```text
@staging.catora.local
```

Passwords must never be committed or entered as workflow inputs/chat/issues.

## 5. Deterministic staging fixtures

The staging deploy runs these one-shot services **before** starting the candidate application:

1. object-storage initialization;
2. `alembic upgrade head` exactly once;
3. `python scripts/seed_enterprise_demo.py`;
4. `python scripts/seed_staging_certification.py`.

`seed_staging_certification.py` is guarded by:

```text
CATORA_STAGING_CERTIFICATION_SEED_CONFIRM=I_UNDERSTAND_THIS_IS_STAGING_ONLY
```

It refuses non-staging QA email suffixes. It creates/upserts owner/admin/analyst/reviewer/viewer test users, ensures their exact QA-workspace membership role, removes their access to the denied workspace, and creates an active no-membership identity with no memberships.

The seed prints fixture identifiers only. It never prints passwords.

The enterprise demo reset is deliberately destructive **only to the dedicated synthetic `sales-demo` staging workspace**. Do not run this staging deployment workflow against production or a client-data environment.

## 6. Automatic staging deployment

`.github/workflows/staging-deploy-compose.yml` listens for a successful `Immutable release images` workflow caused by a push to `main`.

It automatically:

1. resolves the exact release SHA/run;
2. downloads the immutable release manifest from that workflow run;
3. verifies all three component SHAs/run IDs/digests;
4. captures the currently running web/API/worker image references as rollback evidence;
5. validates required staging-only configuration without printing values;
6. pulls the exact digests;
7. starts staging dependencies;
8. initializes storage;
9. runs migrations once;
10. resets deterministic QA data/roles;
11. starts web/API/worker;
12. waits for local runtime readiness;
13. runs `scripts/staging_certify.py` against the configured staging URLs;
14. uploads sanitized certification evidence;
15. fails unless the result is exactly `READY FOR UAT`.

The same workflow can be manually re-run against a specific successful release image workflow run via `workflow_dispatch`.

## 7. Deployment identity chain

Every component receives runtime metadata describing the image actually selected by the Compose deployment:

```text
CATORA_RELEASE_GIT_SHA
CATORA_RELEASE_CI_RUN_ID
CATORA_RELEASE_IMAGE_TAG
CATORA_RELEASE_IMAGE_DIGEST
CATORA_RELEASE_PREVIOUS_IMAGE
```

Certification proves:

```text
release manifest SHA/run/digest
        ↓
runtime web /api/release
runtime API /health/release
runtime worker /health/worker via real Celery task
        ↓
exact match required before product/browser tests
```

Any missing or mismatched runtime identity is `BLOCKED`.

## 8. Browser and direct-API authorization model

Browser login now happens through the web runtime proxy, so session/CSRF cookies are scoped to the web staging origin.

For intentional direct-API RBAC bypass tests, the Playwright certification script extracts the already-authenticated staging session cookie from the web context and sends it explicitly to the staging API. This proves the backend cannot be bypassed even though normal browser traffic uses the proxy.

The cookie value is never printed or stored in evidence.

## 9. Visual baseline approval

The first functional staging run will remain `BLOCKED` until human-approved screenshots exist at:

```text
qa/visual-baselines/desktop-chromium/login.png
qa/visual-baselines/desktop-chromium/workspace.png
qa/visual-baselines/desktop-chromium/products.png
qa/visual-baselines/desktop-chromium/service-visibility.png
qa/visual-baselines/mobile-chromium/login.png
qa/visual-baselines/mobile-chromium/workspace.png
qa/visual-baselines/mobile-chromium/products.png
qa/visual-baselines/mobile-chromium/service-visibility.png
```

A blocked visual run uploads candidate screenshots under its sanitized evidence artifact. A human reviews those images; approved baselines are then added through normal code review. The certification script never updates baselines automatically.

Material differences later produce `VISUAL REVIEW REQUIRED` and remain blocked until reviewed.

## 10. Human UAT

After and only after `READY FOR UAT`, manually run:

```text
Record human UAT decision
```

`.github/workflows/uat-record.yml` downloads the exact staging certification artifact and refuses to proceed unless that artifact says `READY FOR UAT` with complete web/API/worker identity evidence.

The operator records `PASS` or `FAIL`. The workflow creates `catora-uat-attestation.json` containing:

- staging certification run ID;
- QA run ID;
- one exact Git SHA;
- exact component image identities/digests;
- GitHub actor recording the decision;
- timestamp;
- bounded non-sensitive notes.

It does **not** deploy production.

Configure a protected GitHub Environment named `uat` with required human reviewers so the record itself is an explicit approval boundary.

## 11. Production boundary

No production promotion is created or executed by these staging workflows.

A future production promotion workflow must, at minimum:

1. require a `PASS` UAT attestation;
2. verify it points to a `READY FOR UAT` staging certification;
3. deploy the exact recorded web/API/worker digests without rebuilding;
4. require a protected `production` environment approval;
5. capture previous production rollback references;
6. perform only non-destructive production smoke;
7. never mutate live client/payment/location data merely to prove deployment health.

Do not implement or execute production promotion without explicit authorization.
