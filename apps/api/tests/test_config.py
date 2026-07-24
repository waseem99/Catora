from __future__ import annotations

import base64

import pytest

from catora_api.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://user:password@db:5432/catora",
        "s3_secret_key": "production-s3-secret",
        "auth_token_pepper": "p" * 32,
        "frontend_url": "https://catora.codistan.org",
        "cors_origins": ["https://catora.codistan.org"],
        "trust_proxy_headers": True,
        "shopify_enabled": True,
        "shopify_client_id": "client-id-123456",
        "shopify_client_secret": "s" * 32,
        "shopify_callback_url": (
            "https://api.catora.codistan.org/api/v1/shopify/oauth/callback"
        ),
        "shopify_required_scopes": ["read_products"],
        "shopify_expiring_offline_tokens": True,
        "shopify_credential_encryption_key": base64.urlsafe_b64encode(
            b"k" * 32
        ).decode(),
        "shopify_public_enabled": True,
        "shopify_public_client_id": "public-client-id-123456",
        "shopify_public_client_secret": "q" * 32,
        "shopify_public_app_url": "https://shopify.catora.codistan.org",
        "shopify_public_required_scopes": ["read_products"],
        "shopify_public_credential_encryption_key": base64.urlsafe_b64encode(
            b"u" * 32
        ).decode(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_settings_pass() -> None:
    production_settings().validate_production()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"frontend_url": "http://catora.codistan.org"}, "CATORA_FRONTEND_URL"),
        ({"cors_origins": ["http://catora.codistan.org"]}, "CATORA_CORS_ORIGINS"),
        ({"cors_origins": ["https://other.example"]}, "must include"),
        ({"trust_proxy_headers": False}, "CATORA_TRUST_PROXY_HEADERS"),
        (
            {
                "shopify_callback_url": (
                    "http://localhost:8000/api/v1/shopify/oauth/callback"
                )
            },
            "must use HTTPS",
        ),
        (
            {
                "shopify_callback_url": (
                    "https://api.catora.codistan.org/api/v1/shopify/wrong"
                )
            },
            "canonical callback path",
        ),
        ({"shopify_expiring_offline_tokens": False}, "expiring offline tokens"),
        (
            {"shopify_public_app_url": "http://shopify.catora.codistan.org"},
            "HTTPS origin",
        ),
        (
            {"shopify_public_app_url": "https://other.example"},
            "canonical production origin",
        ),
        (
            {"shopify_public_required_scopes": ["read_products", "write_products"]},
            "public Shopify app must request only read_products",
        ),
        (
            {"shopify_public_credential_encryption_key": "not-a-key"},
            "CATORA_SHOPIFY_PUBLIC_CREDENTIAL_ENCRYPTION_KEY",
        ),
    ],
)
def test_invalid_production_settings_fail(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        production_settings(**overrides).validate_production()


def test_disabled_shopify_does_not_require_shopify_secrets() -> None:
    production_settings(
        shopify_enabled=False,
        shopify_client_id="",
        shopify_client_secret="",
        shopify_credential_encryption_key="",
    ).validate_production()


def test_disabled_public_shopify_does_not_require_public_secrets() -> None:
    production_settings(
        shopify_public_enabled=False,
        shopify_public_client_id="",
        shopify_public_client_secret="",
        shopify_public_credential_encryption_key="",
    ).validate_production()
