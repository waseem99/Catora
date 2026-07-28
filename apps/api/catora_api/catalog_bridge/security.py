from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from fastapi import HTTPException, Request, status

from catora_api.config import Settings, get_settings
from catora_api.db.models.catalog import CatalogSource
from catora_api.shopify.crypto import CredentialCipher, CredentialEncryptionError

CATALOG_BRIDGE_CREDENTIAL_SCHEME = "catalog-bridge"


@dataclass(frozen=True, slots=True)
class ProvisionedBridgeCredential:
    token: str
    fingerprint: str
    encrypted_token: str


def credential_reference(source_id: uuid.UUID) -> str:
    return f"{CATALOG_BRIDGE_CREDENTIAL_SCHEME}:{source_id}"


class CatalogBridgeAuthenticator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _cipher(self) -> CredentialCipher:
        return CredentialCipher(self.settings.catalog_bridge_encryption_key_bytes())

    def provision(self, source_id: uuid.UUID) -> ProvisionedBridgeCredential:
        token = secrets.token_urlsafe(48)
        fingerprint = hashlib.sha256(token.encode()).hexdigest()[:12]
        encrypted = self._cipher().encrypt(
            token,
            installation_id=str(source_id),
            shop_domain="catalog-bridge",
            purpose="source-token",
        )
        return ProvisionedBridgeCredential(
            token=token,
            fingerprint=fingerprint,
            encrypted_token=encrypted.value,
        )

    def rotate(self, source: CatalogSource) -> ProvisionedBridgeCredential:
        credential = self.provision(source.id)
        source.credential_ref = credential_reference(source.id)
        source.config = {
            **dict(source.config),
            "bridge_credential": {
                "encrypted_token": credential.encrypted_token,
                "fingerprint": credential.fingerprint,
                "rotated_at": datetime.now(UTC).isoformat(),
            },
        }
        return credential

    async def authenticate(
        self,
        request: Request,
        *,
        source: CatalogSource,
        body: bytes,
    ) -> None:
        if source.source_type != "bridge" or source.deleted_at is not None:
            self._reject("Catalog bridge source is unavailable")
        bridge_credential = source.config.get("bridge_credential")
        if not isinstance(bridge_credential, dict):
            self._reject("Catalog bridge credential is unavailable")
        encrypted = bridge_credential.get("encrypted_token")
        if not isinstance(encrypted, str) or not encrypted:
            self._reject("Catalog bridge credential is unavailable")
        try:
            token = self._cipher().decrypt(
                encrypted,
                installation_id=str(source.id),
                shop_domain="catalog-bridge",
                purpose="source-token",
            )
        except CredentialEncryptionError:
            self._reject("Catalog bridge credential is unavailable")

        timestamp = self._required_header(request.headers, "x-catora-timestamp")
        content_hash = self._required_header(
            request.headers,
            "x-catora-content-sha256",
        )
        idempotency_key = self._required_header(
            request.headers,
            "x-catora-idempotency-key",
        )
        signature = self._required_header(request.headers, "x-catora-signature")
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            self._reject("Catalog bridge timestamp is invalid")
        current = int(datetime.now(UTC).timestamp())
        if abs(current - timestamp_value) > self.settings.catalog_bridge_clock_skew_seconds:
            self._reject("Catalog bridge request timestamp is outside the replay window")
        actual_hash = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual_hash, content_hash):
            self._reject("Catalog bridge content hash does not match the request body")
        if not 8 <= len(idempotency_key) <= 300:
            self._reject("Catalog bridge idempotency key is invalid")

        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        canonical = "\n".join(
            (
                request.method.upper(),
                path,
                timestamp,
                content_hash,
                idempotency_key,
            )
        )
        expected = hmac.new(
            token.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).digest()
        try:
            supplied = self._decode_signature(signature)
        except ValueError:
            self._reject("Catalog bridge signature is invalid")
        if not hmac.compare_digest(expected, supplied):
            self._reject("Catalog bridge signature is invalid")

    @staticmethod
    def _decode_signature(value: str) -> bytes:
        import base64

        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @staticmethod
    def _required_header(headers: Mapping[str, str], name: str) -> str:
        value = headers.get(name)
        if not value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Missing catalog bridge header: {name}",
            )
        return value

    @staticmethod
    def _reject(detail: str) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )
