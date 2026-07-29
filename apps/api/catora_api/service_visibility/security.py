# ruff: noqa: E501
from __future__ import annotations

import hashlib
import hmac
import secrets
import time


def issue_token() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    return token, digest, digest[:12]


def verify_signed_body(
    *,
    token: str,
    expected_token_hash: str,
    timestamp: str,
    signature: str,
    body: bytes,
    max_skew_seconds: int = 300,
) -> None:
    if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected_token_hash):
        raise ValueError("Invalid bridge credential")
    try:
        supplied = int(timestamp)
    except ValueError as exc:
        raise ValueError("Invalid bridge timestamp") from exc
    if abs(int(time.time()) - supplied) > max_skew_seconds:
        raise ValueError("Bridge timestamp is outside the allowed clock skew")
    expected = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid bridge signature")
