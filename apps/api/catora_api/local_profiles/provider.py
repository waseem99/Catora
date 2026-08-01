from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

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
    """Capability-gated placeholder for accepted Google Business Profile accounts.

    The repository deliberately does not hardcode undocumented account/location API operations.
    A concrete runtime adapter must be supplied only after official capability discovery and an
    account-level acceptance record. Until then, calls fail explicitly rather than presenting a
    non-live provider as available.
    """

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
        if False:  # pragma: no cover - keeps this method an async iterator contract
            yield  # type: ignore[misc]
