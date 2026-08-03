# Release integrity

Catora release-bearing changes must keep the database migration graph, ORM metadata, FastAPI routes, typed feature flags, tests, deployment contract and issue evidence synchronized.

## Mandatory validation

Run from the repository root after installing `apps/api[dev]`:

```bash
python -m catora_api.release_integrity
python -m ruff check apps/api
python -m mypy --config-file apps/api/pyproject.toml apps/api/catora_api
python -m pytest apps/api/tests
```

The release-integrity command fails when:

- Alembic has zero, multiple, unexpected, or broken heads;
- a required migration predecessor is missing;
- local-profile, reputation or measurement ORM tables are not registered through `catora_api.db`;
- required FastAPI routes are not registered in the application;
- release-bearing feature flags bypass the typed `Settings` model.

## Migration acceptance

The CI database job must prove this sequence against a clean PostgreSQL database:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

The job also runs the enterprise-demo reset twice and validates the generated Shopify CSV. A migration is not accepted merely because unit tests pass.

## Feature-state rules

`CATORA_LOCAL_PROFILE_INTELLIGENCE_ENABLED`, `CATORA_REPUTATION_INTELLIGENCE_ENABLED` and `CATORA_MEASUREMENT_CONNECTORS_ENABLED` default to `false`. Enabling these flags exposes only the repository-tested synthetic/read-only runtime:

- Google Business Profile access is unavailable until an explicit account-level acceptance exists.
- Reputation response drafts require human approval and cannot be posted by Catora.
- Measurement imports accept only aggregate allowlisted dimensions, expose no live provider-connect route and prohibit causal, ranking, traffic, revenue or ROI claims.
- None of these modules connects Ranchers or another production client account.

## Merge and deployment evidence

A roadmap issue may be closed as completed only after its implementation is merged into `main`, the authoritative workflow suite is green, migrations pass, and the final deployment status is healthy. A branch, draft pull request, local test result, or issue comment is not completion evidence.

Repository settings must require the release-bearing workflow checks on `main`. Changes to those GitHub rules require repository-owner administration and cannot be implemented by application code.
