from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = (
    ROOT
    / "wordpress-service-visibility"
    / "includes"
    / "class-catora-service-visibility.php"
)
WORKFLOW = ROOT.parent / ".github/workflows/service-visibility-contract.yml"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"


def test_wordpress_plugin_resumes_without_silent_truncation() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    assert "CHECKPOINT_OPTION" in source
    assert "accepted_batches" in source
    assert "checkpoint_batch" in source
    assert "MAX_PAGE_COUNT = 10000" in source
    assert "silently truncated" in source
    assert "array_slice( $records, 0, 1000 )" not in source


def test_wordpress_plugin_extracts_promised_public_metadata() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    assert "extract_json_ld" in source
    assert "_yoast_wpseo_canonical" in source
    assert "rank_math_canonical_url" in source
    assert "featured_media" in source
    assert "'author'" in source
    assert "value=\"\"" in source


def test_wordpress_runtime_and_node_lockfile_contracts() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "wordpress:6.8-php8.3-apache" in workflow
    assert "runtime-smoke.php" in workflow
    assert "failed_sequence_one" in workflow
    assert "npm ci --no-audit --no-fund" in ci
    assert "npm ci --ignore-scripts --no-audit --no-fund" in ci
    assert "npm install --package-lock-only" not in ci
    assert "npm run shopify-app:check" in ci
