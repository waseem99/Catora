from __future__ import annotations

import pytest

from catora_api.secrets import (
    EnvironmentSecretResolver,
    SecretResolutionError,
    SecretValue,
)


def test_secret_value_hides_contents_from_repr() -> None:
    secret = SecretValue("private-token")

    assert secret.get_secret_value() == "private-token"
    assert "private-token" not in repr(secret)


def test_environment_resolver_accepts_only_connector_secret_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATORA_CONNECTOR_SECRET_DEMO", " token-value ")
    resolver = EnvironmentSecretResolver()

    assert (
        resolver.resolve(
            "env:CATORA_CONNECTOR_SECRET_DEMO"
        ).get_secret_value()
        == "token-value"
    )

    with pytest.raises(SecretResolutionError, match="not allowed"):
        resolver.resolve("env:UNRELATED_SECRET")


def test_environment_resolver_returns_generic_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CATORA_CONNECTOR_SECRET_MISSING", raising=False)
    resolver = EnvironmentSecretResolver()

    with pytest.raises(SecretResolutionError, match="unavailable") as error:
        resolver.resolve("env:CATORA_CONNECTOR_SECRET_MISSING")

    assert "CATORA_CONNECTOR_SECRET_MISSING" not in str(error.value)

    with pytest.raises(SecretResolutionError, match="Unsupported"):
        resolver.resolve("vault:path/to/secret")
