from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


@dataclass(frozen=True)
class IssuedToken:
    raw: str
    digest: str


class TokenService:
    def __init__(self, pepper: str) -> None:
        if len(pepper) < 16:
            raise ValueError("Token pepper must contain at least 16 characters")
        self._pepper = pepper.encode()

    def issue(self, size: int = 48) -> IssuedToken:
        raw = secrets.token_urlsafe(size)
        return IssuedToken(raw=raw, digest=self.digest(raw))

    def digest(self, raw: str) -> str:
        return hmac.new(self._pepper, raw.encode(), hashlib.sha256).hexdigest()

    def verify(self, raw: str, digest: str) -> bool:
        return hmac.compare_digest(self.digest(raw), digest)


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode()).hexdigest()
