# ADR 0001: Monorepo and runtime boundaries

- **Status:** Accepted
- **Date:** 2026-07-21

## Context

Catora requires an enterprise web application, deterministic analytics, background processing, shared API contracts and optional private browser-side inference. The initial team must move quickly without locking the product into one AI provider or ecommerce platform.

## Decision

Use one repository with:

- Next.js/TypeScript for the web experience and Node.js runtime;
- FastAPI/Python for domain APIs and analytics;
- Celery/Redis for durable background work;
- PostgreSQL as the authoritative database;
- S3-compatible object storage for source and report artifacts;
- Transformers.js for explicitly invoked, low-risk browser-side inference;
- shared Zod schemas for frontend-facing contracts.

## Consequences

- TypeScript and Python boundaries require explicit contracts.
- Browser inference improves privacy and responsiveness but must have a server fallback and cannot determine authoritative metrics.
- Docker Compose supports reproducible demos; production remains container-provider-neutral.
- The repository favors clear package boundaries over independently deployed repositories during MVP development.
