from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from typing import Any, cast
from urllib.parse import urlencode

import pytest

from catora_api.config import Settings
from catora_api.db.models import AuditEvent, CatalogSource, ReportJob
from catora_api.main import app
from catora_api.shopify.crypto import CredentialCipher, CredentialEncryptionError
from catora_api.shopify.installations import (
    SHOPIFY_CUSTOM_REGISTRATION_IDENTITY,
    ShopifyInstallationService,
    normalize_shop_domain,
    parse_credential_reference,
    verify_shopify_query_hmac,
)


class EmptyScalars:
    def all(self) -> list[ReportJob]:
        return []


class PersistSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.refresh_count = 0

    async def scalars(self, _statement: object) -> EmptyScalars:
        return EmptyScalars()

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, CatalogSource | ReportJob) and value.id is None:
                value.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _value: object) -> None:
        self.refresh_count += 1


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


@pytest.mark.asyncio
async def test_custom_installation_persists_registration_provenance() -> None:
    workspace_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()
    state_record = ReportJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        report_type="shopify_oauth_state",
        status="exchanging",
        input_snapshot={"actor_user_id": str(actor_user_id)},
        template_version="shopify-oauth-v1",
    )
    session = PersistSession()

    installation = await ShopifyInstallationService(_settings())._persist_installation(
        cast(Any, session),
        state_record=state_record,
        shop="northstar.myshopify.com",
        token={
            "access_token": "a" * 32,
            "refresh_token": "r" * 32,
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "read_products",
        },
    )

    assert installation.input_snapshot["registration_identity"] == (
        SHOPIFY_CUSTOM_REGISTRATION_IDENTITY
    )
    assert installation.input_snapshot["runtime_environment"] == "development"
    source = next(item for item in session.added if isinstance(item, CatalogSource))
    assert source.config["registration_identity"] == SHOPIFY_CUSTOM_REGISTRATION_IDENTITY
    assert source.config["runtime_environment"] == "development"
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.payload["registration_identity"] == SHOPIFY_CUSTOM_REGISTRATION_IDENTITY
    assert audit.payload["runtime_environment"] == "development"
    assert session.commit_count == 1
    assert session.refresh_count == 1


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
