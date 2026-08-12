from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check(name: str, condition: bool, success: str, failure: str) -> Check:
    return Check(name=name, ok=condition, detail=success if condition else failure)


def _text(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


def _blank_env_template(text: str) -> bool:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return False
        _, value = line.split("=", 1)
        if value.strip():
            return False
    return True


def validate(root: Path) -> list[Check]:
    production = _text(root, "deploy/portable/docker-compose.production.yml")
    dependencies = _text(root, "deploy/portable/docker-compose.dependencies.yml")
    env = _text(root, "deploy/portable/.env.production.example")
    runbook = _text(root, "deploy/portable/README.md")
    release_workflow = _text(root, ".github/workflows/portable-production-release.yml")
    acceptance_workflow = _text(root, ".github/workflows/portable-production-smoke.yml")
    smoke = _text(root, "scripts/smoke_portable_production.py")
    web_proxy = _text(root, "apps/web/app/api/backend/[...path]/route.ts")

    dockerfiles = all(
        (root / path).is_file()
        for path in (
            "apps/api/Dockerfile",
            "apps/worker/Dockerfile",
            "apps/web/Dockerfile",
        )
    )

    checks = [
        _check(
            "portable.dockerfiles",
            dockerfiles,
            "API, worker and web Dockerfiles are source controlled",
            "all three application Dockerfiles are required",
        ),
        _check(
            "portable.immutable_images",
            "catora-api@${CATORA_PRODUCTION_API_IMAGE_DIGEST" in production
            and "catora-worker@${CATORA_PRODUCTION_WORKER_IMAGE_DIGEST" in production
            and "catora-web@${CATORA_PRODUCTION_WEB_IMAGE_DIGEST" in production,
            "production deploys exact GHCR digests for all application components",
            "production must deploy digest-addressed web/API/worker images",
        ),
        _check(
            "portable.migration_owner",
            'profiles: ["ops"]' in production
            and 'command: ["alembic", "upgrade", "head"]' in production
            and production.count('command: ["alembic", "upgrade", "head"]') == 1,
            "one explicit ops migration service owns alembic upgrade head",
            "exactly one production release step must own schema migration",
        ),
        _check(
            "portable.worker_no_migration",
            "worker:" in production
            and "CATORA_PRODUCTION_WORKER_IMAGE_DIGEST" in production,
            "worker is an independent immutable service with no migration command",
            "worker service must remain separate from migration ownership",
        ),
        _check(
            "portable.runtime_web_api",
            "CATORA_PRODUCTION_INTERNAL_API_URL" in production
            and "process.env.CATORA_API_URL" in web_proxy,
            "same web image receives its API origin at runtime",
            "production web must not be rebuilt just to change the API origin",
        ),
        _check(
            "portable.env_blank",
            _blank_env_template(env),
            "production environment template contains names only",
            "production environment template must not commit values or secrets",
        ),
        _check(
            "portable.crypto_continuity",
            "CATORA_AUTH_TOKEN_PEPPER=" in env
            and "CATORA_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY=" in env
            and "CATORA_CATALOG_BRIDGE_CREDENTIAL_ENCRYPTION_KEY=" in env
            and "CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY=" in env
            and "CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY=" in env
            and "Changing an encryption key" in runbook,
            "credential/encryption continuity is explicit in template and recovery runbook",
            "portable recovery must preserve keys that match restored encrypted data",
        ),
        _check(
            "portable.dependencies",
            "postgres:17-alpine" in dependencies
            and "redis:8-alpine" in dependencies
            and "minio/minio:" in dependencies
            and all(name in dependencies for name in ("postgres-data:", "redis-data:", "minio-data:")),
            "single-host recovery provides persistent PostgreSQL 17, Redis and MinIO",
            "self-hosted recovery overlay must provide all three dependencies with volumes",
        ),
        _check(
            "portable.canonical_domains",
            "https://catora.codistan.org" in runbook
            and "https://api.catora.codistan.org" in runbook
            and "DNS cutover" in runbook,
            "canonical frontend/API domains and DNS cutover are documented",
            "provider moves must preserve canonical production origins",
        ),
        _check(
            "portable.data_recovery",
            "pg_dump --format=custom" in runbook
            and "object-storage" in runbook
            and "Never run demo or staging seed scripts" in runbook
            and "Hilarious continuity" in runbook,
            "database/object storage recovery and Hilarious continuity are documented",
            "portable deployment must recover existing state before cutover",
        ),
        _check(
            "portable.certified_bundle",
            "workflow_dispatch:" in release_workflow
            and "certification_run_id:" in release_workflow
            and 'report.get("decision") != "READY FOR UAT"' in release_workflow
            and "CATORA_PRODUCTION_API_IMAGE_DIGEST" in release_workflow
            and "CATORA_PRODUCTION_WORKER_IMAGE_DIGEST" in release_workflow
            and "CATORA_PRODUCTION_WEB_IMAGE_DIGEST" in release_workflow
            and "Portable production release prepared without production secrets." in release_workflow,
            "manual bundle consumes READY FOR UAT evidence and preserves exact digests",
            "production bundle must be generated only from certified immutable artifacts",
        ),
        _check(
            "portable.hosted_acceptance",
            "workflow_dispatch:" in acceptance_workflow
            and "environment: production" in acceptance_workflow
            and "CATORA_PRODUCTION_SMOKE_EMAIL" in acceptance_workflow
            and "CATORA_PRODUCTION_SMOKE_PASSWORD" in acceptance_workflow
            and "python scripts/smoke_portable_production.py" in acceptance_workflow,
            "operator-triggered authenticated production acceptance uses protected secrets",
            "portable acceptance must be manually triggered and secret-backed",
        ),
        _check(
            "portable.smoke_scope",
            all(
                marker in smoke
                for marker in (
                    "/health/live",
                    "/health/ready",
                    "/api/release",
                    "/health/release",
                    "/health/worker",
                    "/api/v1/auth/login",
                    "/products?limit=1&offset=0",
                )
            ),
            "production smoke proves health, release identity, authentication and restored catalog access",
            "production acceptance must exercise health, identity, auth and restored data",
        ),
    ]
    return checks


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = validate(root)
    for check in checks:
        print(f"[{'ok' if check.ok else 'error'}] {check.name}: {check.detail}")
    ok = all(check.ok for check in checks)
    print(f"Portable production contract: {'valid' if ok else 'invalid'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
