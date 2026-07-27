from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
API_VERSION = "2026-07"
APP_NAME = "Catora Catalog Intelligence"
SUBTITLE = "Audit catalog quality and buyer-intent readiness"
SHOP_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUIRED_METADATA_KEYS = {
    "app_name",
    "app_card_subtitle",
    "support_email",
    "support_url",
    "privacy_policy_url",
    "terms_url",
    "review_shop_domain",
    "review_contact_email",
    "direct_listing_url",
    "visibility",
    "registration",
    "api_version",
}
OPERATOR_FIELDS = {
    "support_email",
    "support_url",
    "privacy_policy_url",
    "terms_url",
    "review_shop_domain",
    "review_contact_email",
    "direct_listing_url",
}
REQUIRED_RUNBOOK_SECTIONS = {
    "## Final listing copy",
    "## Screenshot plan",
    "## Reviewer walkthrough",
    "## Production registration checklist",
    "## Release gate",
    "## Rollback procedure",
    "## Merchant support runbook",
    "## API-version calendar",
}
FORBIDDEN_LISTING_CLAIMS = {
    "guaranteed revenue",
    "guaranteed ranking",
    "guaranteed conversion",
    "guaranteed traffic",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def _validate_example(path: Path) -> list[str]:
    values = _load_json(path)
    errors: list[str] = []
    missing = sorted(REQUIRED_METADATA_KEYS - values.keys())
    extra = sorted(values.keys() - REQUIRED_METADATA_KEYS)
    if missing:
        errors.append(f"{path}: missing keys: {', '.join(missing)}")
    if extra:
        errors.append(f"{path}: unexpected keys: {', '.join(extra)}")
    if values.get("app_name") != APP_NAME:
        errors.append(f"{path}: app_name must equal {APP_NAME!r}")
    if values.get("app_card_subtitle") != SUBTITLE:
        errors.append(f"{path}: app_card_subtitle must equal {SUBTITLE!r}")
    if values.get("visibility") != "limited":
        errors.append(f"{path}: visibility must be limited")
    if values.get("registration") != "production":
        errors.append(f"{path}: registration must be production")
    if values.get("api_version") != API_VERSION:
        errors.append(f"{path}: api_version must equal {API_VERSION}")
    for key in sorted(OPERATOR_FIELDS):
        if values.get(key) != "":
            errors.append(f"{path}: example field {key} must remain blank")
    return errors


def _validate_metadata(path: Path) -> tuple[list[str], dict[str, object]]:
    values = _load_json(path)
    errors: list[str] = []
    missing = sorted(REQUIRED_METADATA_KEYS - values.keys())
    if missing:
        errors.append(f"{path}: missing keys: {', '.join(missing)}")
    if values.get("app_name") != APP_NAME:
        errors.append(f"{path}: app_name must equal {APP_NAME!r}")
    if values.get("app_card_subtitle") != SUBTITLE:
        errors.append(f"{path}: app_card_subtitle must equal {SUBTITLE!r}")
    if values.get("visibility") != "limited":
        errors.append(f"{path}: visibility must be limited")
    if values.get("registration") != "production":
        errors.append(f"{path}: registration must be production")
    if values.get("api_version") != API_VERSION:
        errors.append(f"{path}: api_version must equal {API_VERSION}")

    for key in sorted(OPERATOR_FIELDS):
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}: {key} is required")

    for key in ("support_url", "privacy_policy_url", "terms_url"):
        value = values.get(key)
        if isinstance(value, str) and value and not _https_url(value):
            errors.append(f"{path}: {key} must be an HTTPS URL")
    listing_url = values.get("direct_listing_url")
    if isinstance(listing_url, str) and listing_url:
        if not _https_url(listing_url) or urlsplit(listing_url).netloc != "apps.shopify.com":
            errors.append(f"{path}: direct_listing_url must use https://apps.shopify.com")
    for key in ("support_email", "review_contact_email"):
        value = values.get(key)
        if isinstance(value, str) and value and not EMAIL_PATTERN.fullmatch(value):
            errors.append(f"{path}: {key} must be a valid email address")
    shop = values.get("review_shop_domain")
    if isinstance(shop, str) and shop and not SHOP_PATTERN.fullmatch(shop.casefold()):
        errors.append(f"{path}: review_shop_domain must use *.myshopify.com")

    report = {
        "metadata_present": True,
        "registration": values.get("registration"),
        "visibility": values.get("visibility"),
        "api_version": values.get("api_version"),
        "review_shop_sha256": (
            hashlib.sha256(shop.casefold().encode()).hexdigest()
            if isinstance(shop, str) and shop
            else None
        ),
        "support_contact_present": bool(values.get("support_email")),
        "privacy_url_present": bool(values.get("privacy_policy_url")),
        "terms_url_present": bool(values.get("terms_url")),
        "listing_url_present": bool(values.get("direct_listing_url")),
    }
    return errors, report


def _validate_version_policy(path: Path) -> tuple[list[str], dict[str, object]]:
    values = _load_json(path)
    errors: list[str] = []
    required = {
        "admin_api_version",
        "released_on",
        "support_window_months",
        "compatibility_review_due",
        "upgrade_target",
        "upgrade_complete_by",
        "support_end_guardrail",
    }
    missing = sorted(required - values.keys())
    if missing:
        errors.append(f"{path}: missing keys: {', '.join(missing)}")
        return errors, {}
    if values.get("admin_api_version") != API_VERSION:
        errors.append(f"{path}: admin_api_version must equal {API_VERSION}")
    if values.get("support_window_months") != 12:
        errors.append(f"{path}: support_window_months must equal 12")
    try:
        released = date.fromisoformat(str(values["released_on"]))
        review_due = date.fromisoformat(str(values["compatibility_review_due"]))
        upgrade_by = date.fromisoformat(str(values["upgrade_complete_by"]))
        guardrail = date.fromisoformat(str(values["support_end_guardrail"]))
    except ValueError as exc:
        errors.append(f"{path}: date fields must use YYYY-MM-DD: {exc}")
        return errors, {}
    if not released < review_due < upgrade_by < guardrail:
        errors.append(
            f"{path}: expected released_on < compatibility_review_due < "
            "upgrade_complete_by < support_end_guardrail"
        )
    if date.today() > review_due:
        errors.append(
            f"{path}: compatibility review deadline {review_due.isoformat()} has passed"
        )
    return errors, {
        "admin_api_version": values.get("admin_api_version"),
        "compatibility_review_due": values.get("compatibility_review_due"),
        "upgrade_target": values.get("upgrade_target"),
        "upgrade_complete_by": values.get("upgrade_complete_by"),
    }


def _validate_runbook(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    folded = text.casefold()
    errors: list[str] = []
    for section in sorted(REQUIRED_RUNBOOK_SECTIONS):
        if section not in text:
            errors.append(f"{path}: missing section {section}")
    for claim in sorted(FORBIDDEN_LISTING_CLAIMS):
        if claim in folded:
            errors.append(f"{path}: forbidden unsupported claim {claim!r}")
    required_phrases = (
        "read_products",
        "Limited visibility",
        "does not access customers, orders, payments",
        "does not publish changes back to Shopify",
        "must never ask a merchant to send an access token",
    )
    for phrase in required_phrases:
        if phrase.casefold() not in folded:
            errors.append(f"{path}: missing required release statement {phrase!r}")
    return errors


def _validate_production_toml(path: Path) -> list[str]:
    with path.open("rb") as handle:
        values = tomllib.load(handle)
    errors: list[str] = []
    webhooks = values.get("webhooks")
    if not isinstance(webhooks, dict) or webhooks.get("api_version") != API_VERSION:
        errors.append(f"{path}: production webhook API version must equal {API_VERSION}")
    scopes = values.get("access_scopes")
    if not isinstance(scopes, dict) or scopes.get("scopes") != "read_products":
        errors.append(f"{path}: production scope must be exactly read_products")
    build = values.get("build")
    if not isinstance(build, dict) or build.get("automatically_update_urls_on_dev") is not False:
        errors.append(f"{path}: production URLs must not update automatically on dev")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    errors: list[str] = []
    errors.extend(
        _validate_example(ROOT / "shopify/public/review-submission.example.json")
    )
    version_errors, version_report = _validate_version_policy(
        ROOT / "shopify/public/api-version-policy.json"
    )
    errors.extend(version_errors)
    errors.extend(_validate_runbook(ROOT / "docs/shopify-public-release.md"))
    errors.extend(
        _validate_production_toml(
            ROOT / "shopify/public/shopify.app.production.toml.example"
        )
    )

    metadata_report: dict[str, object] = {"metadata_present": False}
    if args.metadata is not None:
        metadata_path = args.metadata
        if not metadata_path.is_absolute():
            metadata_path = ROOT / metadata_path
        try:
            metadata_errors, metadata_report = _validate_metadata(metadata_path)
            errors.extend(metadata_errors)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{metadata_path}: unable to validate: {exc}")

    report = {
        "status": "failed" if errors else "passed",
        "repository_release_contract": not errors,
        "api_version": version_report,
        "submission": metadata_report,
        "error_count": len(errors),
    }
    if args.report is not None:
        report_path = args.report
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if errors:
        for error in errors:
            print(f"[error] {error}", file=sys.stderr)
        return 1
    print("Shopify public release contract: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
