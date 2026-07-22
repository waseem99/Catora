from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

ALLOWED_ENV_PREFIX = "CATORA_CONNECTOR_SECRET_"


class SecretResolutionError(ValueError):
    """Raised without including the secret reference or resolved value."""


@dataclass(frozen=True, slots=True)
class SecretValue:
    _value: str = field(repr=False)

    def get_secret_value(self) -> str:
        return self._value


class SecretResolver(Protocol):
    def resolve(self, reference: str) -> SecretValue: ...


class EnvironmentSecretResolver:
    """Resolve controlled pilot secrets from prefixed environment variables."""

    def resolve(self, reference: str) -> SecretValue:
        scheme, separator, variable_name = reference.partition(":")
        if separator != ":" or scheme != "env":
            raise SecretResolutionError("Unsupported credential reference")
        if not variable_name.startswith(ALLOWED_ENV_PREFIX):
            raise SecretResolutionError("Credential reference is not allowed")
        value = os.environ.get(variable_name)
        if value is None or not value.strip():
            raise SecretResolutionError("Credential is unavailable")
        return SecretValue(value.strip())
