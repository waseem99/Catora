# Catora staging certification

This runbook defines the permanent machine gate between an immutable Catora staging deployment and human UAT.

Control issue: #253. Implementation issues: #254, #255 and #256. Provider-portable release/deployment work is tracked by #252.

## Product-boundary audit

Catora is currently one monorepo:

- `apps/web`: Next.js / React workspace UI;
- `apps/api`: FastAPI application and PostgreSQL-backed domain services;
- `apps/worker`: Celery worker using Redis;
- PostgreSQL, Redis and S3-compatible object storage are runtime dependencies.

The current application roles are `owner`, `admin`, `analyst`, `reviewer` and `viewer`.

The current Catora product does **not** implement a transactional customer storefront, cart, checkout, payment processing, order board, rider workflow or branch Dispatcher role. Staging certification must not claim those generic scenarios as automated coverage. If any such feature is introduced later, its happy path, negative/error behavior, authorization and mobile coverage must be added before the feature is release-complete.

Current high-value end-to-end journeys are authentication/session behavior, workspace/RBAC isolation, enterprise-demo/catalog intelligence, Service Visibility, connector lifecycle checks and report/export generation.

## Release flow

The target flow is:

```text
Code / PR
→ unit/build/security checks
→ immutable staging deployment
→ prove exact running revisions/images
→ automated staging certification
→ READY FOR UAT
→ human UAT
→ explicit production approval
→ promote exact tested artifacts
→ non-destructive production smoke
```

Automated staging success never authorizes production.

## Gate zero: runtime release identity

Every running web/API/worker process must receive these **non-secret** runtime values from the deployment system:

```text
CATORA_RELEASE_GIT_SHA=<exact 40-character source SHA>
CATORA_RELEASE_CI_RUN_ID=<release/image-build GitHub Actions run ID>
CATORA_RELEASE_IMAGE_TAG=<OCI image reference/tag>
CATORA_RELEASE_IMAGE_DIGEST=sha256:<64 hexadecimal characters>
CATORA_RELEASE_PREVIOUS_IMAGE=<previous rollback image/digest, or an explicit first-release sentinel>
```

The values must describe the image that is actually running; they are not caller assertions.

Runtime evidence endpoints:

- Web: `GET /api/release`
- API: `GET /health/release`
- Worker: `GET /health/worker`

`/health/worker` performs a real Celery `catora.system.ping`, so the worker identity is returned by a running worker process rather than copied from the API process.

Certification compares the runtime values to the expected immutable candidate metadata supplied by the deployment pipeline. Missing or mismatched identity is `BLOCKED`. Browser/API tests do not start against an unproven build.

## Runtime gate

After identity is proven, certification requires:

- Web `/login` returns HTML;
- API `/health/live` is healthy;
- API `/health/ready` is healthy;
- readiness reports PostgreSQL, Redis and object storage healthy;
- the existing authenticated enterprise-demo smoke succeeds;
- the Playwright browser/RBAC suite succeeds.

The existing `scripts/smoke_hosted_demo.py` remains the deterministic deep API/product smoke and is reused rather than replaced.

## Browser/RBAC gate

`scripts/staging_browser_certification.py` uses Playwright Chromium for:

- desktop Chromium;
- mobile Chromium using a Pixel 7 device profile.

A permanent staging fixture must provide these identities:

- owner;
- admin;
- analyst;
- reviewer;
- viewer;
- active Catora user with no membership in the QA workspace.

For every role the suite verifies UI login, the exact workspace membership role, members-page behavior, cross-workspace API isolation and logout/session revocation. Analyst/reviewer/viewer identities additionally attempt the member-invitation API directly and require HTTP 403. Owner/admin identities must expose the member-management controls. The no-membership identity must receive HTTP 403 from the protected workspace API and be redirected away from the protected browser route.

The suite also opens the deterministic QA workspace, products, demo/preflight and Service Visibility surfaces with the owner identity.

## GitHub `staging` environment

Create a protected GitHub Environment named `staging`.

### Secrets

Store these values only in the environment secret store:

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

Do not place these values in workflow inputs, issues, pull requests, chat, screenshots or test artifacts.

### Optional environment variable

```text
CATORA_STAGING_RUNNER_LABEL=<GitHub-hosted or private/self-hosted runner label>
```

If staging is private, set this to a runner that already has network access to the staging environment. Do not expose staging publicly merely for Playwright.

## Staging deployment event

The staging deployment workflow must trigger the certification workflow after deployment by sending a GitHub `repository_dispatch` event of type:

```text
catora-staging-deployed
```

Its `client_payload` must contain only non-secret deployment evidence:

```json
{
  "web_url": "https://<staging-web-origin>",
  "api_url": "https://<staging-api-origin>",
  "git_sha": "<40-char-sha>",
  "ci_run_id": "<github-actions-run-id>",
  "web_image_digest": "sha256:<digest>",
  "api_image_digest": "sha256:<digest>",
  "worker_image_digest": "sha256:<digest>",
  "qa_workspace_id": "<qa-workspace-uuid>",
  "denied_workspace_id": "<different-existing-workspace-uuid>",
  "require_shopify": false
}
```

The same fields are available as manual `workflow_dispatch` inputs for controlled recovery/re-runs.

The deployment workflow must not dispatch certification until it has deployed the immutable image digests and injected matching `CATORA_RELEASE_*` values into each running component.

## Shopify and other external providers

`require_shopify=true` makes the existing hosted smoke require the canonical staging Shopify test-store acceptance path. If a required test-store/provider fixture or sandbox is not configured, certification must be `BLOCKED`, never silently PASS.

WordPress/Google/provider-specific staging paths should follow the same rule as deterministic fixtures become available.

## Evidence

Each workflow run writes only sanitized artifacts under `staging-certification-artifacts/`:

- `staging-certification.json`;
- `staging-certification.html`;
- `staging-browser-evidence.json`;
- `hosted-demo-smoke.json` when the mandatory demo smoke reaches report generation.

Artifact retention is seven days by default.

Authenticated browser traces, HAR and video are intentionally disabled in the mandatory suite because they can capture cookies, tokens or provider/customer data. Console evidence is reduced to error counts rather than raw messages. Add richer traces only for explicitly non-sensitive scenarios.

Never upload passwords, cookies, tokens, WordPress bridge credentials, Google service-account JSON, Shopify credentials or raw confidential provider payloads.

## Release decision

The orchestrator can emit only:

### `READY FOR UAT`

All mandatory supported identity, runtime, API/product, browser and authorization checks passed against the proven candidate.

### `FAILED`

The candidate identity is proven, but a reproducible application/security/business assertion failed.

### `BLOCKED`

The candidate cannot be certified because deployment identity, required staging URLs, role identities, deterministic workspace fixtures, provider sandbox prerequisites or infrastructure evidence are incomplete.

A `BLOCKED` run is not a pass.

## Visual regression

Human-approved screenshot baselines remain a required follow-up before #253 can be closed. They must cover stable login/workspace/catalog/Service Visibility surfaces on supported viewports. Baselines must never update automatically in certification. Until approved baselines exist, visual regression remains explicitly `BLOCKED/NOT IMPLEMENTED`; functional and security certification is independent and cannot be waived by visual approval.

## Current operational blockers

At the time this contract was introduced, no permanent provider-neutral staging URLs or immutable staging deployment existed. Therefore the workflow can be source-controlled and unit-validated, but a real release decision remains `BLOCKED` until:

1. #252 publishes/deploys immutable web/API/worker images;
2. a staging host is available;
3. the `staging` GitHub Environment identities are created;
4. deterministic QA and denied workspaces are seeded;
5. the deployment pipeline emits `catora-staging-deployed` with actual digests;
6. the full workflow executes successfully.

Production remains out of scope until explicit human approval.
