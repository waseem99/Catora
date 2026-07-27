from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/validate_shopify_public_release.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shopify_release_validator", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_release_contract_is_valid() -> None:
    module = _module()
    assert module._validate_example(
        ROOT / "shopify/public/review-submission.example.json"
    ) == []
    version_errors, _ = module._validate_version_policy(
        ROOT / "shopify/public/api-version-policy.json"
    )
    assert version_errors == []
    assert module._validate_runbook(ROOT / "docs/shopify-public-release.md") == []
    assert module._validate_production_toml(
        ROOT / "shopify/public/shopify.app.production.toml.example"
    ) == []


def test_real_submission_metadata_requires_authoritative_values(tmp_path: Path) -> None:
    module = _module()
    metadata = json.loads(
        (ROOT / "shopify/public/review-submission.example.json").read_text()
    )
    metadata.update(
        {
            "support_email": "support@catora.example",
            "support_url": "https://catora.example/support",
            "privacy_policy_url": "https://catora.example/privacy",
            "terms_url": "https://catora.example/terms",
            "review_shop_domain": "catora-review.myshopify.com",
            "review_contact_email": "review@catora.example",
            "direct_listing_url": "https://apps.shopify.com/catora-catalog-intelligence",
        }
    )
    path = tmp_path / "review-submission.json"
    path.write_text(json.dumps(metadata))

    errors, report = module._validate_metadata(path)

    assert errors == []
    assert report["metadata_present"] is True
    assert report["registration"] == "production"
    assert report["review_shop_sha256"]
    assert "catora-review" not in json.dumps(report)
