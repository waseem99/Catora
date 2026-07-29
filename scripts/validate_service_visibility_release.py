from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENV_KEYS = {
    "CATORA_SERVICE_VISIBILITY_ENABLED",
    "CATORA_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY",
    "CATORA_SERVICE_VISIBILITY_DRAFTS_ENABLED",
    "CATORA_SERVICE_VISIBILITY_MONITORING_ENABLED",
    "CATORA_SERVICE_VISIBILITY_CLOCK_SKEW_SECONDS",
    "CATORA_SERVICE_VISIBILITY_MAX_BATCH_BYTES",
}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check(name: str, condition: bool, success: str, failure: str) -> CheckResult:
    return CheckResult(name=name, ok=condition, detail=success if condition else failure)


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate(root: Path = ROOT) -> list[CheckResult]:
    env = _read_env(root / ".env.example")
    workflow_path = root / ".github/workflows/service-visibility-contract.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    plugin_dir = root / "apps/wordpress-service-visibility"
    plugin = plugin_dir / "catora-service-visibility.php"
    plugin_builder = root / "apps/wordpress-service-visibility/build-plugin.sh"
    migration = root / "apps/api/alembic/versions/0019_wordpress_service_visibility.py"
    api_route = root / "apps/api/catora_api/api/service_visibility.py"
    analysis = root / "apps/api/catora_api/service_visibility/analysis.py"
    docs = root / "docs/service-visibility/README.md"
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts") if isinstance(package, dict) else None

    missing = REQUIRED_ENV_KEYS - env.keys()
    return [
        _check(
            "env.service_visibility.keys",
            not missing,
            "all service visibility variables documented",
            f"missing variables: {', '.join(sorted(missing))}",
        ),
        _check(
            "env.service_visibility.safe_defaults",
            env.get("CATORA_SERVICE_VISIBILITY_ENABLED") == "false"
            and env.get("CATORA_SERVICE_VISIBILITY_DRAFTS_ENABLED") == "false"
            and env.get("CATORA_SERVICE_VISIBILITY_MONITORING_ENABLED") == "false"
            and env.get("CATORA_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY") == "",
            "runtime, drafts, and monitoring default disabled with a blank secret",
            "service visibility, drafts, and monitoring must default disabled and the secret must be blank",
        ),
        _check(
            "repository.service_visibility.runtime",
            all(path.is_file() for path in (migration, api_route, analysis, plugin, docs)),
            "migration, API, engine, plugin, and documentation present",
            "migration, API, engine, plugin, and documentation are required",
        ),
        _check(
            "plugin.service_visibility.safety",
            "wp_insert_post"
            in "\n".join(path.read_text(encoding="utf-8") for path in plugin_dir.rglob("*.php"))
            and "'draft'"
            in "\n".join(path.read_text(encoding="utf-8") for path in plugin_dir.rglob("*.php"))
            and "wp_update_post"
            not in "\n".join(path.read_text(encoding="utf-8") for path in plugin_dir.rglob("*.php")),
            "plugin creates separate drafts and does not update live posts",
            "plugin must create separate drafts and must not update live posts",
        ),
        _check(
            "workflow.service_visibility.main",
            "branches: [main]" in workflow and "workflow_dispatch:" in workflow,
            "workflow runs on main and supports manual validation",
            "workflow must run on main and support workflow_dispatch",
        ),
        _check(
            "workflow.service_visibility.package_retention",
            "retention-days: 90" in workflow,
            "installable plugin retained for 90 days",
            "installable plugin must be retained for 90 days",
        ),
        _check(
            "package.service_visibility.commands",
            isinstance(scripts, dict)
            and scripts.get("service-visibility:plugin")
            == "bash apps/wordpress-service-visibility/build-plugin.sh"
            and scripts.get("service-visibility:release-check")
            == "python scripts/validate_service_visibility_release.py",
            "root plugin and release-audit commands present",
            "root plugin and release-audit commands are required",
        ),
        _check(
            "plugin.service_visibility.builder",
            plugin_builder.is_file() and "catora-service-visibility.zip" in plugin_builder.read_text(encoding="utf-8"),
            "deterministic plugin builder present",
            "plugin builder must produce catora-service-visibility.zip",
        ),
    ]


def main() -> int:
    results = validate()
    valid = all(result.ok for result in results)
    for result in results:
        marker = "ok" if result.ok else "error"
        print(f"[{marker}] {result.name}: {result.detail}")
    print(f"Service visibility release audit: {'valid' if valid else 'invalid'}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
