from __future__ import annotations

from catora_api.config import Settings, get_settings
from catora_api.enrichment.http_provider import HttpJsonSchemaProvider
from catora_api.enrichment.mock_provider import DeterministicMockProvider
from catora_api.enrichment.provider import ProviderAdapter


def configured_provider(
    *,
    provider_name: str,
    environment: str,
    settings: Settings | None = None,
) -> ProviderAdapter | None:
    if provider_name == "mock" and environment != "production":
        return DeterministicMockProvider()
    configuration = settings or get_settings()
    if provider_name == "http_json" and configuration.enrichment_http_endpoint:
        return HttpJsonSchemaProvider(
            endpoint=configuration.enrichment_http_endpoint,
            api_key=configuration.enrichment_http_api_key,
            model_name=configuration.enrichment_http_model,
            timeout_seconds=configuration.enrichment_http_timeout_seconds,
            max_request_cost_microunits=(
                configuration.enrichment_http_max_request_cost_microunits
            ),
        )
    return None
