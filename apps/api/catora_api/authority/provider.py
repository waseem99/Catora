from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast

from catora_api.authority.models import (
    AuthorityCapability,
    AuthorityObservation,
    AuthorityProvider,
)


class AuthorityProviderError(RuntimeError):
    pass


class AuthorityCapabilityUnavailable(AuthorityProviderError):
    pass


class AuthoritySourceProvider(Protocol):
    async def discover_capabilities(self) -> tuple[AuthorityCapability, ...]: ...

    def observations(
        self,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[AuthorityObservation]: ...


@dataclass(frozen=True, slots=True)
class SyntheticAuthorityProvider:
    items: tuple[AuthorityObservation, ...]

    async def discover_capabilities(self) -> tuple[AuthorityCapability, ...]:
        return (
            AuthorityCapability(
                operation="observations.read",
                state="tested",
                scope="synthetic authority fixture",
                tested_at=max(item.observed_at for item in self.items),
            ),
        )

    async def observations(
        self,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[AuthorityObservation]:
        del checkpoint
        for item in self.items:
            yield item


@dataclass(frozen=True, slots=True)
class UnavailableAuthorityProvider:
    provider: AuthorityProvider
    reason: str

    async def discover_capabilities(self) -> tuple[AuthorityCapability, ...]:
        return (
            AuthorityCapability(
                operation="observations.read",
                state="unavailable",
                scope=self.reason,
            ),
        )

    async def observations(
        self,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[AuthorityObservation]:
        del checkpoint
        raise AuthorityCapabilityUnavailable(
            f"{self.provider} is unavailable: {self.reason}"
        )
        if False:  # pragma: no cover
            yield cast(AuthorityObservation, None)


def unavailable_provider(provider: AuthorityProvider) -> UnavailableAuthorityProvider:
    return UnavailableAuthorityProvider(
        provider=provider,
        reason=(
            "provider terms, account access, quota, legal approval and acceptance testing "
            "have not been completed"
        ),
    )
