from __future__ import annotations

from typing import Protocol

from catora_api.enrichment.types import ProviderRequest, ProviderResponse


class ProviderAdapter(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def estimate_cost_microunits(self, request: ProviderRequest) -> int: ...

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...
