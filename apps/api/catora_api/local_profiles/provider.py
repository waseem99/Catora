from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast

from catora_api.local_profiles.models import (
    LocalProfileObservation,
    LocalProviderAccount,
    ProviderCapability,
)


class LocalProfileProviderError(RuntimeError):
    pass


class LocalProfileCapabilityUnavailable(LocalProfileProviderError):
    pass


class LocalProfileProvider(Protocol):
    async def discover_capabilities(
        self,
        account: LocalProviderAccount,
    ) -> tuple[ProviderCapability, ...]: ...

    def observations(
        self,
        account: LocalProviderAccount,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[LocalProfileObservation]: ...


@dataclass(frozen=True, slots=True)
class SyntheticLocalProfileProvider:
    items: tuple[LocalProfileObservation, ...]

    async def discover_capabilities(
        self,
        account: LocalProviderAccount,
    ) -> tuple[ProviderCapability, ...]:
        return account.capabilities

    async def observations(
        self,
        account: LocalProviderAccount,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[LocalProfileObservation]:
        del account, checkpoint
        for item in self.items:
            yield item


class GoogleBusinessProfileProvider:
    """Fail closed until an official account-level provider acceptance exists."""

    async def discover_capabilities(
        self,
        account: LocalProviderAccount,
    ) -> tuple[ProviderCapability, ...]:
        return account.capabilities

    async def observations(
        self,
        account: LocalProviderAccount,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[LocalProfileObservation]:
        del account, checkpoint
        raise LocalProfileCapabilityUnavailable(
            "Google Business Profile account adapter is not accepted in this runtime"
        )
        if False:  # pragma: no cover - preserves the async iterator contract
            yield cast(LocalProfileObservation, None)
