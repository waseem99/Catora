# Release integrity

Catora release-bearing changes must keep the database migration graph, ORM metadata, FastAPI routes, typed feature flags, tests, deployment contract and issue evidence synchronized.

## Current enforced contract

The source-controlled validator currently requires:

- exactly one Alembic head at revision `0028`;
- the uninterrupted `0022 -> 0023 -> 0024 -> 0025 -> 0026 -> 0027 -> 0028` chain;
- 29 restaurant-platform persistence tables registered in SQLAlchemy metadata;
- 45 local-profile, reputation, measurement, authority, operations-console, monitoring, and pilot-evidence paths in FastAPI OpenAPI output;
- seven typed, default-off feature gates in `Settings`.

The validator is authoritative for the exact table, route, and setting inventory. Documentation must be updated whenever that contract changes.

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
- a required migration predecessor is missing or points at the wrong parent;
- required local-profile, reputation, measurement, authority, operations, monitoring, or pilot-acceptance ORM tables are not registered through `catora_api.db`;
- required FastAPI routes are not registered in the running application;
- any release-bearing feature flag bypasses the typed `Settings` model.

## Migration acceptance

The CI database job must prove this sequence against a clean PostgreSQL database:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

For the current head this exercises `0028 -> 0027 -> 0028` after a clean upgrade from the beginning of the graph. The job also runs the enterprise-demo reset twice and validates the generated Shopify CSV. A migration is not accepted merely because unit tests pass.

## Feature-state rules

The following flags default to `false`:

- `CATORA_LOCAL_PROFILE_INTELLIGENCE_ENABLED`
- `CATORA_REPUTATION_INTELLIGENCE_ENABLED`
- `CATORA_MEASUREMENT_CONNECTORS_ENABLED`
- `CATORA_AUTHORITY_INTELLIGENCE_ENABLED`
- `CATORA_RESTAURANT_OPERATIONS_CONSOLE_ENABLED`
- `CATORA_RESTAURANT_MONITORING_ENABLED`
- `CATORA_RESTAURANT_PILOT_ACCEPTANCE_ENABLED`

Enabling a flag exposes only its repository-tested bounded runtime:

- Local-profile synchronization remains synthetic; Google Business Profile is unavailable until explicit account-level acceptance exists.
- Reputation response drafts require human approval and cannot be posted by Catora.
- Measurement accepts only aggregate allowlisted dimensions, exposes no live provider-connect route, and prohibits causal, ranking, traffic, revenue, and ROI claims.
- Authority intelligence rejects paid-link and spam schemes, cannot publish placements, and cannot send outreach.
- The operations console derives records from persisted evidence, while monitoring records schedules and intended notification state without executing remediation or sending notifications.
- The pilot gate stores plans, evidence checks, readiness hashes, external decisions, and disconnect evidence, but exposes no activation or production synchronization capability.
- None of these modules connects Ranchers or another production client account merely because a flag is enabled.

## Authoritative workflow evidence

Release-bearing changes must pass the applicable repository workflows, including:

- consolidated API, static-analysis, web, and security CI;
- PostgreSQL backup and restore;
- Catalog Bridge contract and release audit;
- Service Visibility and WordPress runtime checks;
- Shopify private/public, lifecycle, scale, and release controls;
- deployment contract and hosted availability;
- Northstar and prospect-isolation validation;
- repository governance.

A workflow that is unexpectedly skipped is not equivalent to a successful required check.

## Merge and deployment evidence

A roadmap issue may be closed as completed only after its implementation is merged into `main`, the authoritative workflow suite is green, migrations pass, and the final Railway API, Railway worker, and Vercel deployment statuses are healthy. A branch, draft pull request, local test result, issue body, or issue comment is not completion evidence by itself.

## External acceptance boundary

Repository readiness is distinct from external activation. Live Shopify stores, WordPress sites, custom-commerce backends, Ranchers systems, Google/provider accounts, organization ownership, independent reviewers, and protected-branch administration require evidence from the actual authorized owners and platforms.

Repository settings must require the release-bearing workflow checks on `main`. Changes to GitHub rulesets, collaborators, ownership, or administrator bypass controls require authorized GitHub administration and cannot be implemented or truthfully accepted by application code.
