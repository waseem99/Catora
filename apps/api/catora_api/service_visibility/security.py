from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request, status

from catora_api.config import Settings, get_settings
from catora_api.db.models.catalog import CatalogSource

SERVICE_VISIBILITY_CREDENTIAL_SCHEME = "service-visibility"


class CredentialEncryptionError(ValueError):
    pass


class _CredentialCipher:
    VERSION = "v1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Credential encryption key must contain 32 bytes")
        self._cipher = AESGCM(key)

    @staticmethod
    def _aad(source_id: str) -> bytes:
        return f"catora:{source_id}:service-visibility:wordpress-site-token".encode()

    def encrypt(self, plaintext: str, *, source_id: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode(),
            self._aad(source_id),
        )
        nonce_text = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
        ciphertext_text = base64.urlsafe_b64encode(ciphertext).decode().rstrip("=")
        return f"{self.VERSION}.{nonce_text}.{ciphertext_text}"

    def decrypt(self, encrypted: str, *, source_id: str) -> str:
        try:
            version, nonce_text, ciphertext_text = encrypted.split(".", 2)
            if version != self.VERSION:
                raise CredentialEncryptionError("Unsupported credential version")
            nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
            ciphertext = base64.urlsafe_b64decode(
                ciphertext_text + "=" * (-len(ciphertext_text) % 4)
            )
            return self._cipher.decrypt(
                nonce,
                ciphertext,
                self._aad(source_id),
            ).decode()
        except (ValueError, UnicodeDecodeError, InvalidTag) as exc:
            raise CredentialEncryptionError("Credential could not be decrypted") from exc


@dataclass(frozen=True, slots=True)
class ProvisionedServiceVisibilityCredential:
    token: str
    fingerprint: str
    encrypted_token: str


def credential_reference(source_id: uuid.UUID) -> str:
    return f"{SERVICE_VISIBILITY_CREDENTIAL_SCHEME}:{source_id}"


class ServiceVisibilityAuthenticator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _cipher(self) -> _CredentialCipher:
        return _CredentialCipher(self.settings.service_visibility_encryption_key_bytes())

    def provision(self, source_id: uuid.UUID) -> ProvisionedServiceVisibilityCredential:
        token = secrets.token_urlsafe(48)
        fingerprint = hashlib.sha256(token.encode()).hexdigest()[:12]
        encrypted = self._cipher().encrypt(token, source_id=str(source_id))
        return ProvisionedServiceVisibilityCredential(
            token=token,
            fingerprint=fingerprint,
            encrypted_token=encrypted,
        )

    def rotate(self, source: CatalogSource) -> ProvisionedServiceVisibilityCredential:
        credential = self.provision(source.id)
        source.credential_ref = credential_reference(source.id)
        source.config = {
            **dict(source.config),
            "service_visibility_credential": {
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
        if source.source_type != "wordpress" or source.deleted_at is not None:
            self._reject("Service visibility source is unavailable")
        credential = source.config.get("service_visibility_credential")
        if not isinstance(credential, dict):
            self._reject("Service visibility credential is unavailable")
        encrypted = credential.get("encrypted_token")
        if not isinstance(encrypted, str) or not encrypted:
            self._reject("Service visibility credential is unavailable")
        try:
            token = self._cipher().decrypt(encrypted, source_id=str(source.id))
        except CredentialEncryptionError:
            self._reject("Service visibility credential is unavailable")

        timestamp = self._required_header(request.headers, "x-catora-timestamp")
        content_hash = self._required_header(request.headers, "x-catora-content-sha256")
        idempotency_key = self._required_header(request.headers, "x-catora-idempotency-key")
        signature = self._required_header(request.headers, "x-catora-signature")
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            self._reject("Service visibility timestamp is invalid")
        current = int(datetime.now(UTC).timestamp())
        if abs(current - timestamp_value) > self.settings.service_visibility_clock_skew_seconds:
            self._reject("Service visibility request timestamp is outside the replay window")
        actual_hash = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual_hash, content_hash):
            self._reject("Service visibility content hash does not match the request body")
        if not 8 <= len(idempotency_key) <= 300:
            self._reject("Service visibility idempotency key is invalid")
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        canonical = "\n".join(
            (request.method.upper(), path, timestamp, content_hash, idempotency_key)
        )
        expected = hmac.new(token.encode(), canonical.encode(), hashlib.sha256).digest()
        try:
            supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        except ValueError:
            self._reject("Service visibility signature is invalid")
        if not hmac.compare_digest(expected, supplied):
            self._reject("Service visibility signature is invalid")

    @staticmethod
    def _required_header(headers: Mapping[str, str], name: str) -> str:
        value = headers.get(name)
        if not value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Missing service visibility header: {name}",
            )
        return value

    @staticmethod
    def _reject(detail: str) -> NoReturn:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
