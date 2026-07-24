from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_URL = "https://shopify.catora.codistan.org"
CALLBACK_URL = f"{APP_URL}/auth/callback"
WEBHOOK_URL = "https://api.catora.codistan.org/api/v1/shopify/webhooks"
API_VERSION = "2026-07"
EXPECTED_TOPICS = {
    "app/uninstalled",
    "products/create",
    "products/update",
    "products/delete",
}


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a TOML table")
    return payload


def _validate(path: Path, *, development: bool) -> list[str]:
    config = _load(path)
    errors: list[str] = []

    if config.get("client_id") != "LINK_WITH_SHOPIFY_CLI":
        errors.append(f"{path}: client_id must remain an unlinked placeholder")
    if config.get("application_url") != APP_URL:
        errors.append(f"{path}: application_url must equal {APP_URL}")
    if config.get("embedded") is not True:
        errors.append(f"{path}: public app must be embedded")

    build = config.get("build")
    expected_auto_urls = development
    auto_urls_valid = (
        isinstance(build, dict)
        and build.get("automatically_update_urls_on_dev") is expected_auto_urls
    )
    if not auto_urls_valid:
        expected = str(expected_auto_urls).lower()
        errors.append(f"{path}: automatically_update_urls_on_dev must be {expected}")

    scopes = config.get("access_scopes")
    if not isinstance(scopes, dict):
        errors.append(f"{path}: access_scopes is required")
    else:
        if scopes.get("scopes") != "read_products":
            errors.append(f"{path}: MVP scope must be exactly read_products")
        if scopes.get("use_legacy_install_flow") is not False:
            errors.append(f"{path}: Shopify managed installation must remain enabled")

    auth = config.get("auth")
    if not isinstance(auth, dict) or auth.get("redirect_urls") != [CALLBACK_URL]:
        errors.append(f"{path}: redirect_urls must contain only {CALLBACK_URL}")

    webhooks = config.get("webhooks")
    if not isinstance(webhooks, dict):
        errors.append(f"{path}: webhooks configuration is required")
        return errors
    if webhooks.get("api_version") != API_VERSION:
        errors.append(f"{path}: webhook API version must equal {API_VERSION}")

    subscriptions = webhooks.get("subscriptions")
    found_topics: set[str] = set()
    invalid_uris: list[str] = []
    if isinstance(subscriptions, list):
        for subscription in subscriptions:
            if not isinstance(subscription, dict):
                continue
            topics = subscription.get("topics")
            if not isinstance(topics, list):
                continue
            found_topics.update(item for item in topics if isinstance(item, str))
            if subscription.get("uri") != WEBHOOK_URL:
                invalid_uris.extend(item for item in topics if isinstance(item, str))
    if found_topics != EXPECTED_TOPICS:
        errors.append(f"{path}: webhook topics must equal {sorted(EXPECTED_TOPICS)}")
    if invalid_uris:
        errors.append(f"{path}: all webhook topics must use {WEBHOOK_URL}")

    serialized = path.read_text(encoding="utf-8").casefold()
    forbidden = ("shpat_", "shprt_", "client_secret", "write_products")
    for value in forbidden:
        if value in serialized:
            errors.append(f"{path}: forbidden credential or write-scope marker {value!r}")
    return errors


def main() -> int:
    paths = (
        (ROOT / "shopify/public/shopify.app.development.toml.example", True),
        (ROOT / "shopify/public/shopify.app.production.toml.example", False),
    )
    errors: list[str] = []
    for path, development in paths:
        try:
            errors.extend(_validate(path, development=development))
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{path}: unable to validate: {exc}")

    if errors:
        for error in errors:
            print(f"[error] {error}", file=sys.stderr)
        return 1
    print("Shopify public app contract: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
