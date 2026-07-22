from __future__ import annotations

import uuid

import httpx
import pytest

from catora_api.config import Settings
from catora_api.enrichment.errors import ProviderContractError
from catora_api.enrichment.http_provider import HttpJsonSchemaProvider
from catora_api.enrichment.provider_factory import configured_provider
from catora_api.enrichment.types import ProviderRequest


def _request() -> ProviderRequest:
    return ProviderRequest(
        request_id=uuid.uuid4(),
        task_type="normalize_attributes",
        prompt_version="enrichment-gateway-v1",
        prompt_fingerprint="a" * 64,
        system_prompt="Return structured catalog candidates.",
        user_payload={"allowed_fields": ["width_mm"]},
        response_schema={"type": "object"},
        max_output_tokens=500,
    )


@pytest.mark.asyncio
async def test_http_provider_sends_versioned_schema_request_without_secret_payload() -> None:
    request = _request()

    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = http_request.content.decode("utf-8")
        assert http_request.headers["authorization"] == "Bearer secret-token-value"
        assert http_request.headers["x-catora-request-id"] == str(request.request_id)
        assert http_request.headers["x-catora-prompt-fingerprint"] == "a" * 64
        assert "secret-token-value" not in body
        assert '"response_schema":{"type":"object"}' in body
        return httpx.Response(
            200,
            json={
                "output": {
                    "candidates": [
                        {
                            "field_key": "width_mm",
                            "proposed_value": 2100,
                            "evidence": [],
                            "inferred": True,
                            "evidence_conflict": False,
                            "claim_type": "fact",
                            "explanation": "Normalized from supplied content.",
                        }
                    ]
                },
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cost_microunits": 400,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HttpJsonSchemaProvider(
            endpoint="https://provider.example/v1/enrich",
            api_key="secret-token-value",
            model_name="catalog-model-v1",
            timeout_seconds=5,
            max_request_cost_microunits=1_000,
            client=client,
        )
        response = await provider.generate(request)

    assert response.provider_name == "http_json"
    assert response.model_name == "catalog-model-v1"
    assert response.usage.cost_microunits == 400
    assert provider.estimate_cost_microunits(request) == 1_000
    assert "secret-token-value" not in repr(provider)


@pytest.mark.asyncio
async def test_http_provider_sanitizes_status_errors() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream-secret-detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HttpJsonSchemaProvider(
            endpoint="https://provider.example/v1/enrich",
            api_key="secret-token-value",
            model_name="catalog-model-v1",
            timeout_seconds=5,
            max_request_cost_microunits=1_000,
            client=client,
        )
        with pytest.raises(ProviderContractError) as exc_info:
            await provider.generate(_request())

    assert str(exc_info.value) == "HTTP enrichment provider returned HTTP 503"
    assert "upstream-secret-detail" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_http_provider_rejects_invalid_contract_and_excess_cost() -> None:
    responses = iter(
        (
            httpx.Response(200, json={"unexpected": True}),
            httpx.Response(
                200,
                json={
                    "output": {"candidates": []},
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost_microunits": 2_000,
                    },
                },
            ),
        )
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HttpJsonSchemaProvider(
            endpoint="https://provider.example/v1/enrich",
            api_key="secret-token-value",
            model_name="catalog-model-v1",
            timeout_seconds=5,
            max_request_cost_microunits=1_000,
            client=client,
        )
        with pytest.raises(ProviderContractError, match="required contract"):
            await provider.generate(_request())
        with pytest.raises(ProviderContractError, match="configured maximum"):
            await provider.generate(_request())


def test_provider_factory_selects_http_adapter_from_configuration() -> None:
    settings = Settings(
        environment="test",
        enrichment_provider="http_json",
        enrichment_http_endpoint="https://provider.example/v1/enrich",
        enrichment_http_api_key="secret-token-value",
        enrichment_http_model="catalog-model-v1",
        enrichment_http_max_request_cost_microunits=1_000,
    )

    provider = configured_provider(
        provider_name="http_json",
        environment="test",
        settings=settings,
    )

    assert isinstance(provider, HttpJsonSchemaProvider)
    assert provider.model_name == "catalog-model-v1"


def test_production_http_provider_requires_https_and_secret() -> None:
    insecure_endpoint = Settings(
        environment="production",
        enrichment_provider="http_json",
        enrichment_http_endpoint="http://provider.example/v1/enrich",
        enrichment_http_api_key="secret-token-value",
        s3_secret_key="production-object-secret",
        auth_token_pepper="p" * 32,
    )
    with pytest.raises(ValueError, match="must use HTTPS"):
        insecure_endpoint.validate_production()

    missing_secret = Settings(
        environment="production",
        enrichment_provider="http_json",
        enrichment_http_endpoint="https://provider.example/v1/enrich",
        enrichment_http_api_key="",
        s3_secret_key="production-object-secret",
        auth_token_pepper="p" * 32,
    )
    with pytest.raises(ValueError, match="must be a production secret"):
        missing_secret.validate_production()

    valid = Settings(
        environment="production",
        enrichment_provider="http_json",
        enrichment_http_endpoint="https://provider.example/v1/enrich",
        enrichment_http_api_key="secret-token-value",
        enrichment_http_model="catalog-model-v1",
        s3_secret_key="production-object-secret",
        auth_token_pepper="p" * 32,
    )
    valid.validate_production()
