from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "docs/governance/repository-authority.json"
EXPECTED_REPOSITORY = "waseem99/Catora"
EXPECTED_OWNER = "waseem99"
EXPECTED_REPOSITORY_URL = "https://github.com/waseem99/Catora"


def fail(message: str) -> None:
    raise SystemExit(f"Repository governance contract failed: {message}")


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid authority record: {exc}")
    if not isinstance(value, dict):
        fail("authority record must be a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> int:
    authority = load_json(AUTHORITY_PATH)
    require(authority.get("repository") == EXPECTED_REPOSITORY, "repository slug mismatch")
    require(authority.get("repository_owner") == EXPECTED_OWNER, "repository owner mismatch")
    require(
        authority.get("canonical_repository_url") == EXPECTED_REPOSITORY_URL,
        "canonical repository URL mismatch",
    )
    require(authority.get("canonical_branch") == "main", "canonical branch must be main")
    require(
        authority.get("verification_scope") == "repository_and_release_authority_only",
        "authority scope must remain repository-only",
    )

    representatives = authority.get("authorized_repository_representatives")
    require(isinstance(representatives, list) and len(representatives) == 1, "one owner representative is required")
    representative = representatives[0]
    require(isinstance(representative, dict), "owner representative must be an object")
    require(representative.get("github_login") == EXPECTED_OWNER, "representative login mismatch")
    require(representative.get("permission") == "admin", "representative must retain admin authority")

    codeowners = read(".github/CODEOWNERS")
    require(f"* @{EXPECTED_OWNER}" in codeowners, "default CODEOWNER is missing")
    require("/docs/governance/ @waseem99" in codeowners, "governance ownership is missing")
    require("/SECURITY.md @waseem99" in codeowners, "security ownership is missing")

    security = read("SECURITY.md")
    support = read("SUPPORT.md")
    ownership = read("docs/governance/repository-ownership.md")
    readme = read("README.md")
    for name, content in (("SECURITY.md", security), ("SUPPORT.md", support), ("ownership record", ownership)):
        require("@waseem99" in content, f"{name} does not identify the owner representative")
    require("SECURITY.md" in readme, "README does not link the security policy")
    require("SUPPORT.md" in readme, "README does not link the support policy")
    require("repository-ownership.md" in readme, "README does not link the authority record")

    package = json.loads(read("package.json"))
    require(isinstance(package, dict), "package.json must be an object")
    repository = package.get("repository")
    require(isinstance(repository, dict), "package.json repository metadata is missing")
    require(
        repository.get("url") == f"git+{EXPECTED_REPOSITORY_URL}.git",
        "package repository metadata is not canonical",
    )
    require(package.get("homepage") == f"{EXPECTED_REPOSITORY_URL}#readme", "package homepage is not canonical")

    shopify_package = json.loads(read("apps/shopify/package.json"))
    require(
        isinstance(shopify_package.get("repository"), dict)
        and shopify_package["repository"].get("url") == f"git+{EXPECTED_REPOSITORY_URL}.git",
        "Shopify package repository metadata is not canonical",
    )

    plugin = read("apps/wordpress-service-visibility/catora-service-visibility.php")
    plugin_readme = read("apps/wordpress-service-visibility/readme.txt")
    require(f"Plugin URI: {EXPECTED_REPOSITORY_URL}" in plugin, "WordPress Plugin URI is not canonical")
    require(f"Author URI: {EXPECTED_REPOSITORY_URL}" in plugin, "WordPress Author URI is not canonical")
    require("Version: 0.2.1" in plugin, "WordPress plugin version must be 0.2.1")
    require("Stable tag: 0.2.1" in plugin_readme, "WordPress stable tag must be 0.2.1")

    workflow_repository = os.environ.get("GITHUB_REPOSITORY")
    workflow_owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if workflow_repository:
        require(workflow_repository == EXPECTED_REPOSITORY, "workflow is running for an unexpected repository")
    if workflow_owner:
        require(workflow_owner == EXPECTED_OWNER, "workflow repository owner mismatch")

    print(f"Repository governance contract valid for {EXPECTED_REPOSITORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
