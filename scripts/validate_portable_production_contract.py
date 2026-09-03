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
    edge = _text(root, "deploy/portable/docker-compose.edge.yml")
    caddyfile = _text(root, "deploy/portable/Caddyfile")
    env = _text(root, "deploy/portable/.env.production.example")
    personal_env = _text(root, "deploy/portable/.env.personal-server.example")
    runbook = _text(root, "deploy/portable/README.md")
    personal_runbook = _text(root, "deploy/portable/PERSONAL_SERVER.md")
    prepare_env = _text(root, "deploy/portable/prepare-personal-server-env.sh")
    preflight = _text(root, "deploy/portable/preflight-personal-server.sh")
    bootstrap_owner = _text(root, "deploy/portable/bootstrap-owner.sh")
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

    certified_sha = "ad44e5d36dc00e75e8d06884ea70e8d37ca27e8b"
    certified_api = "sha256:e97288e821a6bedfb28872f2af92523fef74a919ee20af0ad40fb23a5a37190e"
    certified_worker = "sha256:24285be8126db5c7e99760efff97229c03e1be8fc3884926cc82c7ce9d4a04ae"
    certified_web = "sha256:2515e06268168ba2296d146210e4bd6ce372cdaab6df950d93882cc28698d7b3"

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
            "portable.personal_edge",
            "caddy:" in edge
            and '"80:80"' in edge
            and '"443:443"' in edge
            and "./Caddyfile:/etc/caddy/Caddyfile:ro" in edge
            and "catora.codistan.org" in caddyfile
            and "reverse_proxy web:3000" in caddyfile
            and "api.catora.codistan.org" in caddyfile
            and "reverse_proxy api:8000" in caddyfile,
            "personal-server overlay terminates TLS and proxies canonical web/API domains",
            "personal-server production requires a source-controlled TLS reverse-proxy overlay",
        ),
        _check(
            "portable.personal_certified_release",
            certified_sha in personal_env
            and certified_api in personal_env
            and certified_worker in personal_env
            and certified_web in personal_env
            and "CATORA_PRODUCTION_API_PREVIOUS_IMAGE=none" in personal_env,
            "personal-server template pins the functionally certified immutable first release",
            "personal-server bootstrap must pin all three certified application digests",
        ),
        _check(
            "portable.personal_feature_scope",
            "CATORA_SERVICE_VISIBILITY_ENABLED=true" in personal_env
            and "CATORA_SERVICE_VISIBILITY_DRAFTS_ENABLED=true" in personal_env
            and "CATORA_SERVICE_VISIBILITY_MONITORING_ENABLED=true" in personal_env
            and "CATORA_MEASUREMENT_CONNECTORS_ENABLED=true" in personal_env
            and "CATORA_SHOPIFY_ENABLED=false" in personal_env,
            "personal-server template enables the Hilarious closed-loop capabilities without unrelated connectors",
            "clean production must explicitly enable Service Visibility/measurement and avoid accidental unrelated integrations",
        ),
        _check(
            "portable.personal_secret_generation",
            "secrets.token_urlsafe(48)" in prepare_env
            and "secrets.token_bytes(32)" in prepare_env
            and "0o600" in prepare_env
            and "refusing to overwrite" in prepare_env
            and "print(" not in prepare_env.split("PY\n", 1)[0],
            "personal-server secrets are generated locally into a protected non-overwritten file",
            "personal-server secret bootstrap must generate strong secrets without printing or overwriting them",
        ),
        _check(
            "portable.personal_preflight",
            "x86_64" in preflight
            and "docker compose version" in preflight
            and "TCP port $port is available" in preflight
            and "8 GiB is recommended" in preflight,
            "personal-server preflight checks image architecture, Docker/Compose and edge prerequisites",
            "personal-server deployment must fail early on incompatible architecture or missing Docker prerequisites",
        ),
        _check(
            "portable.clean_bootstrap",
            "/api/v1/auth/bootstrap" in bootstrap_owner
            and "Owner password (12+ characters)" in bootstrap_owner
            and "Do not use any demo or staging seed script" in personal_runbook
            and "old Railway production state is unrecoverable" in personal_runbook
            and "bash deploy/portable/bootstrap-owner.sh" in personal_runbook,
            "clean production uses the real one-time owner bootstrap flow and explicitly avoids demo/staging seeds",
            "unrecoverable Railway state must use clean auth bootstrap, never demo/staging seeds",
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
