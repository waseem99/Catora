from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FRONTEND_URL = "https://catora.codistan.org"
API_URL = "https://api.catora.codistan.org"
SHOPIFY_CALLBACK_URL = f"{API_URL}/api/v1/shopify/oauth/callback"
SHOPIFY_WEBHOOK_URL = f"{API_URL}/api/v1/shopify/webhooks"
SHOPIFY_API_VERSION = "2026-07"
SHOPIFY_TOPICS = {
    "app/uninstalled",
    "products/create",
    "products/update",
    "products/delete",
}
SHOPIFY_SCOPES = {"read_products"}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_toml(path: Path) -> dict[str, Any]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a TOML table")
    return payload


def _read_env_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _check(name: str, condition: bool, success: str, failure: str) -> CheckResult:
    return CheckResult(name=name, ok=condition, detail=success if condition else failure)


def _shopify_checks(root: Path) -> list[CheckResult]:
    config = _read_toml(root / "shopify.app.toml.example")
    results = [
        _check(
            "shopify.application_url",
            config.get("application_url") == FRONTEND_URL,
            "canonical frontend URL",
            f"must equal {FRONTEND_URL}",
        ),
        _check(
            "shopify.embedded",
            config.get("embedded") is False,
            "standalone OAuth flow",
            "must be false for Catora's standalone onboarding flow",
        ),
    ]

    auth = config.get("auth")
    redirect_urls = auth.get("redirect_urls") if isinstance(auth, dict) else None
    results.append(
        _check(
            "shopify.redirect_urls",
            redirect_urls == [SHOPIFY_CALLBACK_URL],
            "canonical callback only",
            f"must contain only {SHOPIFY_CALLBACK_URL}",
        )
    )

    webhooks = config.get("webhooks")
    api_version = webhooks.get("api_version") if isinstance(webhooks, dict) else None
    subscriptions = webhooks.get("subscriptions") if isinstance(webhooks, dict) else None
    results.append(
        _check(
            "shopify.webhooks.api_version",
            api_version == SHOPIFY_API_VERSION,
            f"API {SHOPIFY_API_VERSION}",
            f"must equal {SHOPIFY_API_VERSION}",
        )
    )

    found_topics: set[str] = set()
    invalid_uris: list[str] = []
    if isinstance(subscriptions, list):
        for subscription in subscriptions:
            if not isinstance(subscription, dict):
                continue
            topics = subscription.get("topics")
            uri = subscription.get("uri")
            if isinstance(topics, list):
                found_topics.update(topic for topic in topics if isinstance(topic, str))
                if uri != SHOPIFY_WEBHOOK_URL:
                    invalid_uris.extend(topic for topic in topics if isinstance(topic, str))
    results.extend(
        [
            _check(
                "shopify.webhooks.topics",
                found_topics == SHOPIFY_TOPICS,
                "all four app-level topics and no extras",
                "must contain exactly app/uninstalled and product create/update/delete",
            ),
            _check(
                "shopify.webhooks.uri",
                not invalid_uris and bool(found_topics),
                "all app-level topics use the canonical endpoint",
                f"every subscription must use {SHOPIFY_WEBHOOK_URL}",
            ),
        ]
    )

    access_scopes = config.get("access_scopes")
    scopes_value = access_scopes.get("scopes") if isinstance(access_scopes, dict) else None
    scopes = (
        {scope.strip() for scope in scopes_value.split(",") if scope.strip()}
        if isinstance(scopes_value, str)
        else set()
    )
    results.append(
        _check(
            "shopify.access_scopes",
            scopes == SHOPIFY_SCOPES,
            "read_products only",
            "must request exactly read_products and no write scopes",
        )
    )
    return results


def _provider_checks(root: Path) -> list[CheckResult]:
    vercel = _read_json(root / "apps/web/vercel.json")
    api = _read_json(root / "deploy/railway/api.railway.json")
    worker = _read_json(root / "deploy/railway/worker.railway.json")

    vercel_build = str(vercel.get("buildCommand", ""))
    vercel_install = str(vercel.get("installCommand", ""))
    api_build = api.get("build") if isinstance(api.get("build"), dict) else {}
    api_deploy = api.get("deploy") if isinstance(api.get("deploy"), dict) else {}
    worker_build = worker.get("build") if isinstance(worker.get("build"), dict) else {}
    worker_deploy = worker.get("deploy") if isinstance(worker.get("deploy"), dict) else {}
    predeploy = api_deploy.get("preDeployCommand")

    return [
        _check(
            "vercel.frontend",
            vercel.get("framework") == "nextjs"
            and "npm ci" in vercel_install
            and "@catora/web" in vercel_build,
            "Next.js workspace build configured",
            "must install from the monorepo and build @catora/web",
        ),
        _check(
            "railway.api.dockerfile",
            api_build.get("builder") == "DOCKERFILE"
            and api_build.get("dockerfilePath") == "apps/api/Dockerfile",
            "FastAPI Dockerfile configured",
            "must use apps/api/Dockerfile",
        ),
        _check(
            "railway.api.migrations",
            isinstance(predeploy, list) and "alembic upgrade head" in predeploy,
            "API owns migrations",
            "must run alembic upgrade head before API deployment",
        ),
        _check(
            "railway.api.healthcheck",
            api_deploy.get("healthcheckPath") == "/health/ready",
            "dependency readiness healthcheck configured",
            "must use /health/ready",
        ),
        _check(
            "railway.worker.dockerfile",
            worker_build.get("builder") == "DOCKERFILE"
            and worker_build.get("dockerfilePath") == "apps/worker/Dockerfile",
            "Celery worker Dockerfile configured",
            "must use apps/worker/Dockerfile",
        ),
        _check(
            "railway.worker.migrations",
            "preDeployCommand" not in worker_deploy,
            "worker does not own migrations",
            "worker must not run schema migrations",
        ),
    ]


def _environment_template_checks(root: Path) -> list[CheckResult]:
    values = _read_env_example(root / ".env.example")
    required_keys = {
        "CATORA_SHOPIFY_ENABLED",
        "CATORA_SHOPIFY_CLIENT_ID",
        "CATORA_SHOPIFY_CLIENT_SECRET",
        "CATORA_SHOPIFY_CALLBACK_URL",
        "CATORA_SHOPIFY_REQUIRED_SCOPES",
        "CATORA_SHOPIFY_EXPIRING_OFFLINE_TOKENS",
        "CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY",
    }
    missing = required_keys - values.keys()
    secret_keys = {
        "CATORA_SHOPIFY_CLIENT_ID",
        "CATORA_SHOPIFY_CLIENT_SECRET",
        "CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY",
    }
    return [
        _check(
            "env.shopify.keys",
            not missing,
            "all Shopify variables documented",
            "missing required Shopify environment variable names",
        ),
        _check(
            "env.shopify.secret_defaults",
            all(values.get(key, "__missing__") == "" for key in secret_keys),
            "secret examples are blank",
            "Shopify secret examples must never contain values",
        ),
        _check(
            "env.shopify.safe_defaults",
            values.get("CATORA_SHOPIFY_ENABLED") == "false"
            and values.get("CATORA_SHOPIFY_REQUIRED_SCOPES") == '["read_products"]'
            and values.get("CATORA_SHOPIFY_EXPIRING_OFFLINE_TOKENS") == "true",
            "disabled locally, minimum scope, expiring offline tokens",
            "Shopify defaults must remain disabled and read-only",
        ),
    ]


def _package_checks(root: Path) -> list[CheckResult]:
    package = _read_json(root / "package.json")
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    return [
        _check(
            "package.deployment_commands",
            scripts.get("deploy:validate") == "python scripts/validate_deployment_contract.py"
            and "demo:package-shopify" in scripts
            and scripts.get("demo:smoke") == "python scripts/smoke_hosted_demo.py"
            and scripts.get("demo:verify-shopify-change")
            == "python scripts/verify_shopify_live_change.py",
            "deployment, package, hosted smoke and live-change commands available",
            "package scripts must expose deploy:validate, demo:package-shopify, "
            "demo:smoke and demo:verify-shopify-change",
        )
    ]


def validate(root: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for builder in (
        _shopify_checks,
        _provider_checks,
        _environment_template_checks,
        _package_checks,
    ):
        try:
            checks.extend(builder(root))
        except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            checks.append(CheckResult(builder.__name__, False, f"unable to validate: {exc}"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Catora's source-controlled production deployment contract."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to validate.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    results = validate(args.root.resolve())
    ok = all(result.ok for result in results)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "checks": [asdict(result) for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for result in results:
            marker = "ok" if result.ok else "error"
            print(f"[{marker}] {result.name}: {result.detail}")
        print(f"Deployment contract: {'valid' if ok else 'invalid'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
