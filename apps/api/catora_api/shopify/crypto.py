from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialEncryptionError(ValueError):
    """Raised without exposing ciphertext, keys, or decrypted values."""


@dataclass(frozen=True, slots=True)
class EncryptedCredential:
    value: str = field(repr=False)


class CredentialCipher:
    VERSION = "v1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Credential encryption key must contain 32 bytes")
        self._cipher = AESGCM(key)

    @staticmethod
    def _aad(*, installation_id: str, shop_domain: str, purpose: str) -> bytes:
        return f"catora:{installation_id}:{shop_domain}:{purpose}".encode()

    def encrypt(
        self,
        plaintext: str,
        *,
        installation_id: str,
        shop_domain: str,
        purpose: str,
    ) -> EncryptedCredential:
        if not plaintext:
            raise ValueError("Credential cannot be empty")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode(),
            self._aad(
                installation_id=installation_id,
                shop_domain=shop_domain,
                purpose=purpose,
            ),
        )
        nonce_text = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
        ciphertext_text = base64.urlsafe_b64encode(ciphertext).decode().rstrip("=")
        return EncryptedCredential(
            f"{self.VERSION}.{nonce_text}.{ciphertext_text}"
        )

    def decrypt(
        self,
        encrypted: str,
        *,
        installation_id: str,
        shop_domain: str,
        purpose: str,
    ) -> str:
        try:
            version, nonce_text, ciphertext_text = encrypted.split(".", 2)
            if version != self.VERSION:
                raise CredentialEncryptionError("Unsupported credential version")
            nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
            ciphertext = base64.urlsafe_b64decode(
                ciphertext_text + "=" * (-len(ciphertext_text) % 4)
            )
            plaintext = self._cipher.decrypt(
                nonce,
                ciphertext,
                self._aad(
                    installation_id=installation_id,
                    shop_domain=shop_domain,
                    purpose=purpose,
                ),
            )
            return plaintext.decode()
        except (ValueError, UnicodeDecodeError, InvalidTag) as exc:
            raise CredentialEncryptionError("Credential could not be decrypted") from exc
