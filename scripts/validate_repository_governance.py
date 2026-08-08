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
EXPECTED_WORDPRESS_PLUGIN_VERSION = "0.2.3"
EXPECTED_CONTINUITY_CONTROLS = {
    "administrator_bypass_failure_test",
    "backup_repository_administrator",
    "independent_approving_reviewer",
    "organization_or_shared_administrative_ownership",
    "private_continuity_acceptance_record",
    "protected_main_ruleset",
}


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
    require(authority.get("schema_version") == "1.1", "authority schema version mismatch")
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
    require(
        isinstance(representatives, list) and len(representatives) == 1,
        "one owner representative is required",
    )
    representative = representatives[0]
    require(isinstance(representative, dict), "owner representative must be an object")
    require(representative.get("github_login") == EXPECTED_OWNER, "representative login mismatch")
    require(representative.get("permission") == "admin", "representative must retain admin authority")

    continuity = authority.get("continuity")
    require(isinstance(continuity, dict), "continuity record must be an object")
    require(continuity.get("evaluated_on") == "2026-08-03", "continuity date mismatch")
    require(
        continuity.get("status") == "pending_external_admin_acceptance",
        "continuity must remain pending until independent acceptance exists",
    )
    require(
        continuity.get("repository_owner_type") == "personal_user",
        "current personal repository ownership must remain explicit",
    )
    require(
        continuity.get("verified_repository_admin_count") == 1,
        "verified repository administrator count mismatch",
    )
    require(
        continuity.get("verified_independent_reviewer_count") == 0,
        "independent reviewer count must not be fabricated",
    )
    branch_inventory = continuity.get("branch_inventory")
    require(isinstance(branch_inventory, dict), "branch inventory must be an object")
    require(branch_inventory.get("count") == 1, "branch inventory count must be one")
    require(branch_inventory.get("branches") == ["main"], "branch inventory must contain main only")
    required_controls = continuity.get("required_controls")
    require(
        isinstance(required_controls, list)
        and set(required_controls) == EXPECTED_CONTINUITY_CONTROLS,
        "continuity required controls mismatch",
    )

    codeowners = read(".github/CODEOWNERS")
    require(f"* @{EXPECTED_OWNER}" in codeowners, "default CODEOWNER is missing")
    require("/docs/governance/ @waseem99" in codeowners, "governance ownership is missing")
    require("/SECURITY.md @waseem99" in codeowners, "security ownership is missing")

    security = read("SECURITY.md")
    support = read("SUPPORT.md")
    license_notice = read("LICENSE")
    ownership = read("docs/governance/repository-ownership.md")
    continuity_policy = read("docs/governance/repository-continuity.md")
    authorization_template = read(".github/ISSUE_TEMPLATE/external-owner-authorization.yml")
    readme = read("README.md")
    for name, content in (
        ("SECURITY.md", security),
        ("SUPPORT.md", support),
        ("ownership record", ownership),
    ):
        require("@waseem99" in content, f"{name} does not identify the owner representative")
    require(
        "repository-continuity.md" in ownership,
        "ownership record does not link the continuity policy",
    )
    require(
        "pending_external_admin_acceptance" in continuity_policy,
        "continuity policy does not expose the pending state",
    )
    require(
        "Private recovery material must never be committed" in continuity_policy,
        "continuity policy does not protect recovery material",
    )
    require(
        "A bot, GitHub App, shared credential or alternate account controlled by the same person"
        in continuity_policy,
        "continuity policy does not define independent review",
    )
    require("SECURITY.md" in readme, "README does not link the security policy")
    require("SUPPORT.md" in readme, "README does not link the support policy")
    require("LICENSE" in readme, "README does not link the proprietary notice")
    require("repository-ownership.md" in readme, "README does not link the authority record")
    require("No copyright" in license_notice, "proprietary notice is incomplete")
    require(
        "confidential evidence is not included" in authorization_template,
        "external authorization template must prohibit confidential evidence",
    )

    package = json.loads(read("package.json"))
    require(isinstance(package, dict), "package.json must be an object")
    repository = package.get("repository")
    require(isinstance(repository, dict), "package.json repository metadata is missing")
    require(
        repository.get("url") == f"git+{EXPECTED_REPOSITORY_URL}.git",
        "package repository metadata is not canonical",
    )
    require(
        package.get("homepage") == f"{EXPECTED_REPOSITORY_URL}#readme",
        "package homepage is not canonical",
    )
    require(package.get("license") == "UNLICENSED", "private root package must remain unlicensed")

    shopify_package = json.loads(read("apps/shopify/package.json"))
    require(
        isinstance(shopify_package.get("repository"), dict)
        and shopify_package["repository"].get("url") == f"git+{EXPECTED_REPOSITORY_URL}.git",
        "Shopify package repository metadata is not canonical",
    )
    require(
        shopify_package.get("license") == "UNLICENSED",
        "private Shopify package must remain unlicensed",
    )

    api_project = read("apps/api/pyproject.toml")
    require(
        f'Repository = "{EXPECTED_REPOSITORY_URL}"' in api_project,
        "API project repository URL is not canonical",
    )

    plugin = read("apps/wordpress-service-visibility/catora-service-visibility.php")
    plugin_readme = read("apps/wordpress-service-visibility/readme.txt")
    require(f"Plugin URI: {EXPECTED_REPOSITORY_URL}" in plugin, "WordPress Plugin URI is not canonical")
    require(f"Author URI: {EXPECTED_REPOSITORY_URL}" in plugin, "WordPress Author URI is not canonical")
    require(
        f"Version: {EXPECTED_WORDPRESS_PLUGIN_VERSION}" in plugin,
        f"WordPress plugin version must be {EXPECTED_WORDPRESS_PLUGIN_VERSION}",
    )
    require("Requires PHP: 7.4" in plugin, "WordPress plugin must declare PHP 7.4 support")
    require(
        f"Stable tag: {EXPECTED_WORDPRESS_PLUGIN_VERSION}" in plugin_readme,
        f"WordPress stable tag must be {EXPECTED_WORDPRESS_PLUGIN_VERSION}",
    )
    require(
        "Requires PHP: 7.4" in plugin_readme,
        "WordPress readme must declare PHP 7.4 support",
    )

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
