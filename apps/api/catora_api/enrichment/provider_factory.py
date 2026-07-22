from __future__ import annotations

from catora_api.enrichment.mock_provider import DeterministicMockProvider
from catora_api.enrichment.provider import ProviderAdapter


def configured_provider(
    *,
    provider_name: str,
    environment: str,
) -> ProviderAdapter | None:
    if provider_name == "mock" and environment != "production":
        return DeterministicMockProvider()
    return None
