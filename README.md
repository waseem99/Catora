# Catora

**Catora — AI Commerce Intelligence**

Catora audits enterprise ecommerce catalogs, identifies data and discoverability gaps, tests conversational buyer intents, proposes evidence-backed improvements, and packages the results into controlled operational workflows and executive reports.

This repository contains the production-shaped MVP and the prepared client-winning demonstration described in [the client demo guide](docs/client-demo.md). A commit is release-ready only when the validation and deployment evidence described in [the release-integrity runbook](docs/release-integrity.md) is green.

## Governance and verified authority

The GitHub repository owner and authorized repository-side representative is [`@waseem99`](https://github.com/waseem99). Repository administration, review routing, release provenance, and the limits of that verification are documented in [the repository ownership record](docs/governance/repository-ownership.md), [the continuity policy](docs/governance/repository-continuity.md), and the machine-readable authority record.

The current closeout state is recorded in [the August 3, 2026 repository audit](docs/governance/repository-closeout-audit-2026-08-03.md). Source-controlled implementation and deployments are ready for continued development. Shared organization ownership, an independent reviewer, protected-`main` enforcement evidence, and external client/provider authorization remain human-admin or external-system gates and are not represented as complete.

Use [SECURITY.md](SECURITY.md) for vulnerability reporting, [SUPPORT.md](SUPPORT.md) for repository support, and [LICENSE](LICENSE) for the proprietary rights notice. Authorization for external domains, stores, customer systems, and commercial pilots must still come from the actual system or business owner; GitHub ownership does not replace platform, legal, or client authorization.

## Client demo quick start

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
npm run demo:seed
```

Sign in with `demo@catora.local` and the password printed by the seed command, select **Northstar Living — Sales Demo**, then choose **Launch client demo**.

The seed command recreates only the dedicated sales-demo workspace. See [docs/client-demo.md](docs/client-demo.md) for the eight-minute presenter flow, reset command and failure fallback.

## Architecture

- **Web:** Next.js 16 and React 19 on Node.js 22
- **API:** FastAPI and Python 3.13
- **Database:** PostgreSQL
- **Background jobs:** Celery and Redis
- **Object storage:** S3-compatible storage through MinIO locally
- **Browser-side intelligence:** Transformers.js with WebGPU/WASM capability detection
- **Contracts:** shared TypeScript/Zod schemas

The browser intelligence package is intentionally limited to privacy-preserving, low-risk local inference. Server-side analytics remain deterministic, and higher-value AI tasks use a provider-neutral backend gateway.

## Local development

### Prerequisites

- Node.js 22+
- Python 3.13+
- Docker with Compose for the complete local stack

```bash
cp .env.example .env
npm install
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'apps/api[dev]'
```

Run the API:

```bash
cd apps/api
fastapi dev catora_api/main.py --port 8000
```

Run the web application in another terminal:

```bash
npm run dev
```

Open `http://localhost:3000`.

## CSV catalog ingestion

The first usable ingestion path supports authenticated, tenant-scoped CSV uploads and resumable background processing.

1. Upload raw CSV bytes to `PUT /api/v1/workspaces/{workspace_id}/catalog-uploads/csv` using a CSV content type.
2. Create a source with `POST /api/v1/workspaces/{workspace_id}/catalog-sources`, supplying the returned object key and column mapping.
3. Validate the source through `POST /api/v1/workspaces/{workspace_id}/catalog-sources/{source_id}/validate`.
4. Queue ingestion through `POST /api/v1/workspaces/{workspace_id}/catalog-sources/{source_id}/jobs`.
5. Inspect job status and raw source samples through the workspace ingestion endpoints.

Writes require a valid CSRF token for cookie-authenticated sessions. CSV uploads are streamed and default to a 25 MiB limit configured through `CATORA_MAX_CATALOG_UPLOAD_BYTES`. Ordinary job responses exclude raw rejected rows; detailed source samples remain restricted to authorized catalog managers.

## Restaurant intelligence boundaries

The restaurant platform is implemented through Alembic revision `0028`: canonical restaurant evidence, the signed Catalog Bridge profile, restaurant audit and answer-readiness evaluation, governed Git proposals, local-profile and reputation intelligence, aggregate measurement, authority intelligence, the operations console, monitoring records, and the generic production-pilot acceptance gate.

All provider- or pilot-facing modules remain feature-gated off by default. The repository-tested runtime is synthetic, evidence-only, read-only, or draft-only as appropriate:

- Google Business Profile and other live profile providers are unavailable until account-level acceptance exists.
- Reputation response drafts require human review and cannot be posted by Catora.
- Measurement accepts only aggregate allowlisted dimensions and prohibits causal, ranking, traffic, revenue, and ROI claims.
- Authority intelligence cannot buy links, publish placements, or send outreach.
- Operations monitoring records intended actions and notification state but cannot execute remediation or send notifications.
- The pilot gate records evidence and external decisions but permanently exposes no live activation capability.
- No Ranchers production account, repository, database, provider, ordering flow, pricing, or availability system is connected.

See [the release-integrity runbook](docs/release-integrity.md) and the module runbooks under `docs/`.

## Validation

```bash
npm run check
python scripts/validate_repository_governance.py
python -m catora_api.release_integrity
python3 -m ruff check apps/api
python3 -m mypy --config-file apps/api/pyproject.toml apps/api/catora_api
python3 -m pytest apps/api/tests
```

## Database migrations

```bash
cd apps/api
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

A successful clean upgrade and downgrade/re-upgrade cycle is required before a migration-bearing pull request can be merged.

## Repository layout

```text
apps/web                    Next.js enterprise interface
apps/api                    FastAPI application and shared worker package
apps/worker                 Celery runtime container
packages/contracts          Shared TypeScript API contracts
packages/browser-intelligence  Private browser-side inference adapter
docs/adr                    Architecture decisions
```

## Engineering rules

- All analytical numbers are computed deterministically.
- AI-generated values must carry evidence, confidence, model and prompt versions.
- Tenant boundaries are enforced in backend queries, not only in the UI.
- No catalog write occurs without explicit approval.
- Secrets must never be committed or emitted in logs.
- An issue is not complete until merged code, green workflows, migrations and deployment evidence agree.
