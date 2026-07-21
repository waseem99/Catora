# Catora

**Catora — AI Commerce Intelligence**

Catora audits enterprise ecommerce catalogs, identifies data and discoverability gaps, tests conversational buyer intents, proposes evidence-backed improvements, and packages the results into controlled operational workflows and executive reports.

This repository currently contains the production-shaped foundation for the MVP described in [Issue #1](https://github.com/waseem99/Catora/issues/1).

## Architecture

- **Web:** Next.js 16 and React 19 on Node.js 22
- **API:** FastAPI and Python 3.13
- **Database:** PostgreSQL
- **Background jobs:** Celery and Redis
- **Object storage:** S3-compatible storage through MinIO locally
- **Browser-side intelligence:** Transformers.js with WebGPU/WASM capability detection
- **Contracts:** shared TypeScript/Zod schemas

The browser intelligence package is intentionally limited to privacy-preserving, low-risk local inference. Server-side analytics remain deterministic, and higher-value AI tasks use a provider-neutral backend gateway in later issues.

## Quick start

### Prerequisites

- Node.js 22+
- Python 3.13+
- Docker with Compose for the complete local stack

### Local application development

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

### Complete local stack

```bash
cp .env.example .env
docker compose up --build
```

Services:

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| Mailpit | http://localhost:8025 |

## Validation

```bash
npm run check
python3 -m ruff check apps/api
python3 -m mypy --config-file apps/api/pyproject.toml apps/api/catora_api
python3 -m pytest apps/api/tests
```

## Database migrations

```bash
cd apps/api
alembic upgrade head
alembic downgrade -1
```

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
