from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast

from catora_api.measurement.models import (
    MeasurementObservation,
    MeasurementProperty,
    MeasurementProvider,
    MeasurementProviderCapability,
)


class MeasurementProviderError(RuntimeError):
    pass


class MeasurementCapabilityUnavailable(MeasurementProviderError):
    pass


class MeasurementSourceProvider(Protocol):
    async def discover_capabilities(
        self,
    ) -> tuple[MeasurementProviderCapability, ...]: ...

    async def discover_properties(self) -> tuple[MeasurementProperty, ...]: ...

    def observations(
        self,
        property: MeasurementProperty,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[MeasurementObservation]: ...


@dataclass(frozen=True, slots=True)
class SyntheticMeasurementProvider:
    properties: tuple[MeasurementProperty, ...]
    items: tuple[MeasurementObservation, ...]

    async def discover_capabilities(
        self,
    ) -> tuple[MeasurementProviderCapability, ...]:
        tested_at = max(item.observed_at for item in self.items)
        return (
            MeasurementProviderCapability(
                operation="properties.read",
                state="tested",
                scope="synthetic aggregate fixture",
                tested_at=tested_at,
            ),
            MeasurementProviderCapability(
                operation="observations.read",
                state="tested",
                scope="synthetic aggregate fixture",
                tested_at=tested_at,
            ),
        )

    async def discover_properties(self) -> tuple[MeasurementProperty, ...]:
        return self.properties

    async def observations(
        self,
        property: MeasurementProperty,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[MeasurementObservation]:
        del checkpoint
        for item in self.items:
            if item.external_property_id == property.external_property_id:
                yield item


@dataclass(frozen=True, slots=True)
class UnavailableMeasurementProvider:
    provider: MeasurementProvider
    reason: str

    async def discover_capabilities(
        self,
    ) -> tuple[MeasurementProviderCapability, ...]:
        return (
            MeasurementProviderCapability(
                operation="properties.read",
                state="unavailable",
                scope=self.reason,
            ),
            MeasurementProviderCapability(
                operation="observations.read",
                state="unavailable",
                scope=self.reason,
            ),
        )

    async def discover_properties(self) -> tuple[MeasurementProperty, ...]:
        raise MeasurementCapabilityUnavailable(
            f"{self.provider} property discovery is unavailable: {self.reason}"
        )

    async def observations(
        self,
        property: MeasurementProperty,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[MeasurementObservation]:
        del property, checkpoint
        raise MeasurementCapabilityUnavailable(
            f"{self.provider} observation access is unavailable: {self.reason}"
        )
        if False:  # pragma: no cover
            yield cast(MeasurementObservation, None)


def unavailable_provider(provider: MeasurementProvider) -> UnavailableMeasurementProvider:
    return UnavailableMeasurementProvider(
        provider=provider,
        reason=(
            "account-level OAuth, property access, quota, legal approval, and acceptance "
            "testing have not been completed"
        ),
    )
