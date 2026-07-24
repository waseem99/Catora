from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from catora_api.config import Settings
from catora_api.main import app
from catora_api.shopify.public_session import (
    ShopifyPublicSessionError,
    ShopifyPublicTokenExchange,
    ShopifyPublicTokenExchangeError,
    bearer_session_token,
    verify_shopify_public_session_token,
)

CLIENT_ID = "public-client-123456"
CLIENT_SECRET = "q" * 32
ACCESS_VALUE = "a" * 32
REFRESH_VALUE = "r" * 32
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _encode(value: object) -> str:
    payload = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _session_token(
    *,
    secret: str = CLIENT_SECRET,
    claims: dict[str, object] | None = None,
    header: dict[str, object] | None = None,
) -> str:
    issued = int((NOW - timedelta(seconds=10)).timestamp())
    payload: dict[str, object] = {
        "iss": "https://prospect-store.myshopify.com/admin",
        "dest": "https://prospect-store.myshopify.com",
        "aud": CLIENT_ID,
        "sub": "42",
        "exp": int((NOW + timedelta(seconds=50)).timestamp()),
        "nbf": issued,
        "iat": issued,
        "jti": "f8912129-1af6-4cad-9ca3-76b0f7621087",
        "sid": "session-id-123",
    }
    payload.update(claims or {})
    encoded_header = _encode(header or {"alg": "HS256", "typ": "JWT"})
    encoded_payload = _encode(payload)
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(
        secret.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{signing_input}.{encoded_signature}"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "shopify_public_enabled": True,
        "shopify_public_client_id": CLIENT_ID,
        "shopify_public_client_secret": CLIENT_SECRET,
        "shopify_public_app_url": "http://localhost:3001",
        "shopify_public_required_scopes": ["read_products"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_shopify_public_session_is_verified() -> None:
    session = verify_shopify_public_session_token(
        _session_token(),
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        now=NOW,
    )

    assert session.shop_domain == "prospect-store.myshopify.com"
    assert session.user_id == "42"
    assert session.issued_at == NOW - timedelta(seconds=10)
    assert session.expires_at == NOW + timedelta(seconds=50)
    assert session.token_id == "f8912129-1af6-4cad-9ca3-76b0f7621087"
    assert session.session_id == "session-id-123"


@pytest.mark.parametrize(
    ("token", "message"),
    [
        (_session_token(secret="w" * 32), "signature"),
        (_session_token(claims={"aud": "another-client"}), "audience"),
        (
            _session_token(
                claims={
                    "exp": int((NOW - timedelta(seconds=10)).timestamp()),
                }
            ),
            "expired",
        ),
        (
            _session_token(
                claims={
                    "nbf": int((NOW + timedelta(seconds=20)).timestamp()),
                }
            ),
            "not active",
        ),
        (
            _session_token(
                claims={
                    "iss": "https://other-store.myshopify.com/admin",
                }
            ),
            "issuer",
        ),
        (
            _session_token(
                claims={
                    "dest": "https://prospect-store.myshopify.com/admin",
                }
            ),
            "dest",
        ),
        (_session_token(header={"alg": "none", "typ": "JWT"}), "HS256"),
    ],
)
def test_invalid_shopify_public_sessions_fail_closed(
    token: str,
    message: str,
) -> None:
    with pytest.raises(ShopifyPublicSessionError, match=message):
        verify_shopify_public_session_token(
            token,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            now=NOW,
        )


def test_bearer_session_token_requires_exact_authorization_scheme() -> None:
    token = _session_token()
    assert bearer_session_token(f"Bearer {token}") == token
    with pytest.raises(ShopifyPublicSessionError, match="Bearer"):
        bearer_session_token(f"Basic {token}")
    with pytest.raises(ShopifyPublicSessionError, match="required"):
        bearer_session_token(None)


@pytest.mark.asyncio
async def test_token_exchange_requests_expiring_offline_access() -> None:
    session_token = _session_token()
    verified = verify_shopify_public_session_token(
        session_token,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        now=NOW,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://prospect-store.myshopify.com/admin/oauth/access_token"
        )
        form = parse_qs(request.content.decode())
        assert form == {
            "client_id": [CLIENT_ID],
            "client_secret": [CLIENT_SECRET],
            "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
            "subject_token": [session_token],
            "subject_token_type": ["urn:ietf:params:oauth:token-type:id_token"],
            "requested_token_type": [
                "urn:shopify:params:oauth:token-type:offline-access-token"
            ],
            "expiring": ["1"],
        }
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_VALUE,
                "refresh_token": REFRESH_VALUE,
                "expires_in": 3600,
                "refresh_token_expires_in": 7_776_000,
                "scope": "read_products",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        bundle = await ShopifyPublicTokenExchange(
            _settings(),
            client=client,
        ).exchange(
            session_token=session_token,
            session=verified,
        )

    assert bundle.granted_scopes == ("read_products",)
    assert bundle.expires_in == 3600
    assert bundle.refresh_token_expires_in == 7_776_000
    assert ACCESS_VALUE not in repr(bundle)
    assert REFRESH_VALUE not in repr(bundle)


@pytest.mark.asyncio
async def test_token_exchange_rejects_scope_expansion() -> None:
    token = _session_token()
    verified = verify_shopify_public_session_token(
        token,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        now=NOW,
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_VALUE,
                "refresh_token": REFRESH_VALUE,
                "expires_in": 3600,
                "refresh_token_expires_in": 7_776_000,
                "scope": "read_products,write_products",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(
            ShopifyPublicTokenExchangeError,
            match="scopes",
        ):
            await ShopifyPublicTokenExchange(
                _settings(),
                client=client,
            ).exchange(
                session_token=token,
                session=verified,
            )


def test_public_session_route_is_registered_without_secret_fields() -> None:
    schema = app.openapi()
    route = "/api/v1/shopify/public/session"
    assert route in schema["paths"]
    serialized = str(schema["paths"][route]).casefold()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
