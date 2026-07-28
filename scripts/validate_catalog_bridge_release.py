from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENV_KEYS = {
    "CATORA_CATALOG_BRIDGE_ENABLED",
    "CATORA_CATALOG_BRIDGE_CREDENTIAL_ENCRYPTION_KEY",
    "CATORA_CATALOG_BRIDGE_CLOCK_SKEW_SECONDS",
    "CATORA_CATALOG_BRIDGE_MAX_BATCH_BYTES",
}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check(name: str, condition: bool, success: str, failure: str) -> CheckResult:
    return CheckResult(name=name, ok=condition, detail=success if condition else failure)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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
    package = _read_json(root / "packages/catalog-bridge/package.json")
    workflow = (root / ".github/workflows/catalog-bridge-contract.yml").read_text(
        encoding="utf-8"
    )
    migration = root / "apps/api/alembic/versions/0018_catalog_bridge_source.py"
    api_route = root / "apps/api/catora_api/api/catalog_bridge.py"
    readme = root / "packages/catalog-bridge/README.md"

    missing = REQUIRED_ENV_KEYS - env.keys()
    results = [
        _check(
            "env.catalog_bridge.keys",
            not missing,
            "all catalog bridge variables documented",
            f"missing variables: {', '.join(sorted(missing))}",
        ),
        _check(
            "env.catalog_bridge.safe_defaults",
            env.get("CATORA_CATALOG_BRIDGE_ENABLED") == "false"
            and env.get("CATORA_CATALOG_BRIDGE_CREDENTIAL_ENCRYPTION_KEY") == "",
            "disabled by default and secret example blank",
            "bridge must default disabled and the encryption-key example must be blank",
        ),
        _check(
            "package.catalog_bridge.identity",
            package.get("name") == "@catora/catalog-bridge"
            and package.get("version") == "0.1.0",
            "versioned catalog bridge package",
            "package name/version must remain @catora/catalog-bridge 0.1.0 for this release",
        ),
        _check(
            "package.catalog_bridge.runtime",
            package.get("dependencies") == {}
            and isinstance(package.get("bin"), dict)
            and package["bin"].get("catora-bridge") == "./dist/cli.js",
            "self-contained runtime and CLI entrypoint",
            "package must have no runtime dependencies and expose catora-bridge",
        ),
        _check(
            "workflow.catalog_bridge.main",
            "branches: [main]" in workflow and "workflow_dispatch:" in workflow,
            "runs on main and supports manual release validation",
            "workflow must run on main and support workflow_dispatch",
        ),
        _check(
            "workflow.catalog_bridge.package_retention",
            "retention-days: 90" in workflow,
            "installable package retained for 90 days",
            "installable package must be retained for 90 days",
        ),
        _check(
            "repository.catalog_bridge.runtime_files",
            migration.is_file() and api_route.is_file() and readme.is_file(),
            "migration, API route and developer README present",
            "migration, API route and developer README are required",
        ),
    ]
    return results


def main() -> int:
    results = validate()
    ok = all(result.ok for result in results)
    for result in results:
        marker = "ok" if result.ok else "error"
        print(f"[{marker}] {result.name}: {result.detail}")
    print(f"Catalog bridge release audit: {'valid' if ok else 'invalid'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
