from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from catora_api.enrichment.errors import BudgetExceededError, InvalidProviderOutputError
from catora_api.enrichment.mock_provider import DeterministicMockProvider
from catora_api.enrichment.types import (
    EnrichmentRequest,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    SourceDocument,
)
from catora_api.intents.parser import BuyerIntentParsingService


class QueueProvider:
    provider_name = "test-provider"
    model_name = "intent-model-v1"

    def __init__(self, outputs: Sequence[dict[str, object]], *, estimate: int = 100) -> None:
        self.outputs = list(outputs)
        self.requests: list[ProviderRequest] = []
        self.estimate = estimate

    def estimate_cost_microunits(self, _request: ProviderRequest) -> int:
        return self.estimate

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            output=self.outputs.pop(0),
            usage=ProviderUsage(
                input_tokens=10,
                output_tokens=5,
                cost_microunits=50,
            ),
        )


def _valid_output() -> dict[str, object]:
    return {
        "query": "provider text is not authoritative",
        "category_keys": ["sofas"],
        "hard_constraints": [
            {
                "field_key": "width",
                "operator": "less_than_or_equal",
                "expected": 210,
                "unit": "cm",
            }
        ],
        "soft_preferences": [],
        "market_id": None,
        "locale": None,
    }


@pytest.mark.asyncio
async def test_parser_retries_invalid_output_and_preserves_authoritative_query() -> None:
    provider = QueueProvider(
        [
            {**_valid_output(), "category_keys": ["beds"]},
            _valid_output(),
        ]
    )
    service = BuyerIntentParsingService(
        provider,
        budget_microunits=500,
        max_attempts=2,
    )

    result = await service.parse(
        "  compact   sofa under 210 cm  ",
        allowed_category_keys=("sofas",),
        allowed_field_keys=("width",),
        locale="en-GB",
    )

    assert result.structured_intent.query == "compact sofa under 210 cm"
    assert result.structured_intent.category_keys == ("sofas",)
    assert result.structured_intent.locale == "en-GB"
    assert result.attempt_count == 2
    assert result.input_tokens == 20
    assert result.output_tokens == 10
    assert result.cost_microunits == 100


@pytest.mark.asyncio
async def test_parser_redacts_secrets_from_provider_payload() -> None:
    provider = QueueProvider([_valid_output()])
    service = BuyerIntentParsingService(provider, budget_microunits=200)
    original = "Email buyer@example.com and use token ghp_12345678901234567890 for a sofa"

    result = await service.parse(original, allowed_category_keys=("sofas",))

    payload_query = provider.requests[0].user_payload["untrusted_query"]
    assert payload_query == "Email [REDACTED_EMAIL] and use [REDACTED_SECRET] for a sofa"
    assert result.structured_intent.query == original


@pytest.mark.asyncio
async def test_parser_rejects_fields_outside_allowlist() -> None:
    provider = QueueProvider([_valid_output()])
    service = BuyerIntentParsingService(provider, budget_microunits=200, max_attempts=1)

    with pytest.raises(InvalidProviderOutputError, match="field keys outside"):
        await service.parse(
            "compact sofa",
            allowed_category_keys=("sofas",),
            allowed_field_keys=("height",),
        )


@pytest.mark.asyncio
async def test_mock_provider_returns_editable_structured_preview() -> None:
    market_id = uuid.uuid4()
    result = await BuyerIntentParsingService(
        DeterministicMockProvider(),
        budget_microunits=200,
    ).parse(
        "weather resistant outdoor chair",
        allowed_category_keys=("outdoor_furniture",),
        market_id=market_id,
        locale="en-US",
    )

    assert result.provider_name == "mock"
    assert result.structured_intent.query == "weather resistant outdoor chair"
    assert result.structured_intent.category_keys == ("outdoor_furniture",)
    assert result.structured_intent.market_id == market_id
    assert result.structured_intent.locale == "en-US"


@pytest.mark.asyncio
async def test_parser_stops_before_exceeding_budget() -> None:
    provider = QueueProvider([_valid_output()], estimate=300)
    service = BuyerIntentParsingService(provider, budget_microunits=200)

    with pytest.raises(BudgetExceededError, match="budget would be exceeded"):
        await service.parse("compact sofa")

    assert provider.requests == []


def test_provider_request_accepts_parser_task_without_expanding_enrichment_tasks() -> None:
    request = ProviderRequest(
        request_id=uuid.uuid4(),
        task_type="parse_buyer_intent",
        prompt_version="buyer-intent-parser-v1",
        prompt_fingerprint="a" * 64,
        system_prompt="Return JSON.",
        user_payload={"untrusted_query": "compact sofa"},
        response_schema={"type": "object"},
        max_output_tokens=500,
    )
    assert request.task_type == "parse_buyer_intent"

    with pytest.raises(ValidationError):
        EnrichmentRequest(
            workspace_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            task_type="parse_buyer_intent",
            allowed_fields=("width",),
            sources=(
                SourceDocument(
                    source_record_id=uuid.uuid4(),
                    field_path="product.title",
                    content="compact sofa",
                    kind="source_copy",
                ),
            ),
        )


