from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from catora_api.config import Settings
from catora_api.shopify.installations import normalize_shop_domain

_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_ID_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
_OFFLINE_TOKEN_TYPE = "urn:shopify:params:oauth:token-type:offline-access-token"


class ShopifyPublicSessionError(ValueError):
    pass


class ShopifyPublicTokenExchangeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyPublicSession:
    shop_domain: str
    user_id: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    token_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class ShopifyPublicTokenBundle:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    granted_scopes: tuple[str, ...]
    expires_in: int
    refresh_token_expires_in: int


def _decode_segment(value: str, *, label: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ShopifyPublicSessionError(
            f"Shopify session token has an invalid {label} segment"
        ) from exc


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShopifyPublicSessionError(
            f"Shopify session token {label} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ShopifyPublicSessionError(
            f"Shopify session token {label} must be a JSON object"
        )
    return value


def _integer_claim(claims: Mapping[str, object], name: str) -> int:
    value = claims.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ShopifyPublicSessionError(
            f"Shopify session token is missing a valid {name} claim"
        )
    return value


def _text_claim(claims: Mapping[str, object], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise ShopifyPublicSessionError(
            f"Shopify session token is missing a valid {name} claim"
        )
    return value


def _shop_from_dest(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise ShopifyPublicSessionError(
            "Shopify session token dest must be a permanent HTTPS shop origin"
        )
    try:
        return normalize_shop_domain(parsed.hostname)
    except ValueError as exc:
        raise ShopifyPublicSessionError(
            "Shopify session token dest is not a permanent myshopify.com domain"
        ) from exc


def _validate_issuer(value: str, *, shop_domain: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != shop_domain
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path.rstrip("/") != "/admin"
        or parsed.query
        or parsed.fragment
    ):
        raise ShopifyPublicSessionError(
            "Shopify session token issuer does not match its destination shop"
        )


def verify_shopify_public_session_token(
    token: str,
    *,
    client_id: str,
    client_secret: str,
    now: datetime | None = None,
    clock_skew_seconds: int = 5,
) -> ShopifyPublicSession:
    if not token or len(token) > 16_384 or token.strip() != token:
        raise ShopifyPublicSessionError("Shopify session token is malformed")
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise ShopifyPublicSessionError("Shopify session token must be a signed JWT")
    header_segment, payload_segment, signature_segment = parts
    header = _json_object(
        _decode_segment(header_segment, label="header"),
        label="header",
    )
    claims = _json_object(
        _decode_segment(payload_segment, label="payload"),
        label="payload",
    )
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise ShopifyPublicSessionError(
            "Shopify session token must use the HS256 JWT contract"
        )

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = hmac.new(
        client_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    supplied_signature = _decode_segment(signature_segment, label="signature")
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise ShopifyPublicSessionError("Shopify session token signature is invalid")

    audience = _text_claim(claims, "aud")
    if not hmac.compare_digest(audience, client_id):
        raise ShopifyPublicSessionError(
            "Shopify session token audience does not match this app"
        )

    destination = _text_claim(claims, "dest")
    shop_domain = _shop_from_dest(destination)
    _validate_issuer(_text_claim(claims, "iss"), shop_domain=shop_domain)

    exp = _integer_claim(claims, "exp")
    nbf = _integer_claim(claims, "nbf")
    iat = _integer_claim(claims, "iat")
    current = now or datetime.now(UTC)
    current_timestamp = int(current.timestamp())
    if exp <= current_timestamp - clock_skew_seconds:
        raise ShopifyPublicSessionError("Shopify session token has expired")
    if nbf > current_timestamp + clock_skew_seconds:
        raise ShopifyPublicSessionError("Shopify session token is not active yet")
    if iat > current_timestamp + clock_skew_seconds:
        raise ShopifyPublicSessionError(
            "Shopify session token issue time is in the future"
        )
    if not iat <= nbf < exp:
        raise ShopifyPublicSessionError(
            "Shopify session token lifecycle claims are inconsistent"
        )

    return ShopifyPublicSession(
        shop_domain=shop_domain,
        user_id=_text_claim(claims, "sub"),
        issued_at=datetime.fromtimestamp(iat, tz=UTC),
        not_before=datetime.fromtimestamp(nbf, tz=UTC),
        expires_at=datetime.fromtimestamp(exp, tz=UTC),
        token_id=_text_claim(claims, "jti"),
        session_id=_text_claim(claims, "sid"),
    )


def bearer_session_token(authorization: str | None) -> str:
    if authorization is None:
        raise ShopifyPublicSessionError(
            "A Shopify session token is required"
        )
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not token:
        raise ShopifyPublicSessionError(
            "Authorization must use a Shopify Bearer session token"
        )
    return token


class ShopifyPublicTokenExchange:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    async def exchange(
        self,
        *,
        session_token: str,
        session: ShopifyPublicSession,
    ) -> ShopifyPublicTokenBundle:
        self.settings.validate_shopify_public()
        endpoint = (
            f"https://{session.shop_domain}/admin/oauth/access_token"
        )
        form = {
            "client_id": self.settings.shopify_public_client_id,
            "client_secret": self.settings.shopify_public_client_secret,
            "grant_type": _TOKEN_EXCHANGE_GRANT,
            "subject_token": session_token,
            "subject_token_type": _ID_TOKEN_TYPE,
            "requested_token_type": _OFFLINE_TOKEN_TYPE,
            "expiring": "1",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.shopify_public_http_timeout_seconds
        )
        try:
            response = await client.post(
                endpoint,
                data=form,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app token exchange failed"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if not isinstance(payload, dict):
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app token exchange returned an invalid response"
            )
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        refresh_expires_in = payload.get("refresh_token_expires_in")
        scope_value = payload.get("scope")
        if not isinstance(access_token, str) or not access_token:
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app token exchange did not return an access token"
            )
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app token exchange did not return a refresh token"
            )
        if (
            not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app access-token expiry is invalid"
            )
        if (
            not isinstance(refresh_expires_in, int)
            or isinstance(refresh_expires_in, bool)
            or refresh_expires_in <= 0
        ):
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app refresh-token expiry is invalid"
            )
        if not isinstance(scope_value, str):
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app token exchange did not return scopes"
            )
        scopes = tuple(
            sorted({scope.strip() for scope in scope_value.split(",") if scope.strip()})
        )
        required = tuple(sorted(self.settings.shopify_public_required_scopes))
        if scopes != required:
            raise ShopifyPublicTokenExchangeError(
                "Shopify public app granted scopes do not match read_products"
            )
        return ShopifyPublicTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scopes=scopes,
            expires_in=expires_in,
            refresh_token_expires_in=refresh_expires_in,
        )
