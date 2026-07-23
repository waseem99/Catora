from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from urllib.parse import urlencode

import pytest

from catora_api.config import Settings
from catora_api.main import app
from catora_api.shopify.crypto import CredentialCipher, CredentialEncryptionError
from catora_api.shopify.installations import (
    ShopifyInstallationService,
    normalize_shop_domain,
    parse_credential_reference,
    verify_shopify_query_hmac,
)


def _key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode()


def _signing_value() -> str:
    return "-".join(("fixture", "client", "signing", "value", "for", "tests"))


def _settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "shopify_enabled": True,
        "shopify_client_id": "test-client-id",
        "shopify_client_secret": _signing_value(),
        "shopify_callback_url": (
            "https://api.catora.codistan.org/api/v1/shopify/oauth/callback"
        ),
        "shopify_credential_encryption_key": _key(),
        "shopify_required_scopes": ["read_products"],
    }
    values.update(updates)
    return Settings(**values)


def test_shop_domain_requires_permanent_myshopify_hostname() -> None:
    assert normalize_shop_domain("https://Northstar-Living.myshopify.com/") == (
        "northstar-living.myshopify.com"
    )
    with pytest.raises(ValueError):
        normalize_shop_domain("northstar.example.com")
    with pytest.raises(ValueError):
        normalize_shop_domain("northstar.myshopify.com/admin")


def test_shopify_query_hmac_verification_is_order_independent() -> None:
    signing_key = _signing_value()
    unsigned = [
        ("shop", "northstar.myshopify.com"),
        ("code", "authorization-code"),
        ("state", "nonce"),
        ("timestamp", "1770000000"),
    ]
    message = urlencode(sorted(unsigned))
    digest = hmac.new(
        signing_key.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    query = [("timestamp", "1770000000"), ("hmac", digest), *unsigned[:-1]]
    assert verify_shopify_query_hmac(query, client_secret=signing_key)
    assert not verify_shopify_query_hmac(
        [(key, "tampered" if key == "code" else value) for key, value in query],
        client_secret=signing_key,
    )


def test_credential_cipher_uses_authenticated_installation_context() -> None:
    installation_id = str(uuid.uuid4())
    cipher = CredentialCipher(bytes(range(32)))
    fixture = "opaque-access-credential-value"
    encrypted = cipher.encrypt(
        fixture,
        installation_id=installation_id,
        shop_domain="northstar.myshopify.com",
        purpose="access",
    )
    assert fixture not in encrypted.value
    assert (
        cipher.decrypt(
            encrypted.value,
            installation_id=installation_id,
            shop_domain="northstar.myshopify.com",
            purpose="access",
        )
        == fixture
    )
    with pytest.raises(CredentialEncryptionError):
        cipher.decrypt(
            encrypted.value,
            installation_id=installation_id,
            shop_domain="another.myshopify.com",
            purpose="access",
        )


def test_shopify_settings_fail_closed_on_scope_expansion() -> None:
    settings = _settings(shopify_required_scopes=["read_products", "write_products"])
    with pytest.raises(ValueError, match="only read_products"):
        settings.validate_shopify()


def test_authorization_url_requests_offline_minimum_scope() -> None:
    service = ShopifyInstallationService(_settings())
    url = service.authorization_url(
        shop="northstar.myshopify.com",
        state="nonce-value",
    )
    assert "scope=read_products" in url
    assert "state=nonce-value" in url
    assert "grant_options" not in url
    assert "write_products" not in url


def test_credential_reference_is_strict() -> None:
    installation_id = uuid.uuid4()
    assert parse_credential_reference(
        f"shopify-installation:{installation_id}"
    ) == installation_id
    with pytest.raises(ValueError):
        parse_credential_reference(f"env:{installation_id}")


def test_shopify_installation_routes_never_expose_tokens() -> None:
    schema = app.openapi()
    paths = set(schema["paths"])
    assert "/api/v1/workspaces/{workspace_id}/shopify/installations/start" in paths
    assert "/api/v1/workspaces/{workspace_id}/shopify/installation" in paths
    serialized = str(schema).casefold()
    assert "encrypted_access_token" not in serialized
    assert "encrypted_refresh_token" not in serialized
