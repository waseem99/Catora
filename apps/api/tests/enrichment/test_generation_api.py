from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.api.recommendations import (
    configured_provider,
    generate_recommendation,
)
from catora_api.auth.service import AuthContext, AuthorizationError, AuthService
from catora_api.config import Settings
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.enrichment.execution import (
    RecommendationGenerationService,
    RecommendationTargetError,
)
from catora_api.enrichment.gateway import EnrichmentGateway
from catora_api.enrichment.mock_provider import DeterministicMockProvider
from catora_api.enrichment.types import (
    BrandControls,
    EnrichmentRequest,
    ProviderRequest,
    ProviderResponse,
    SourceDocument,
)
from catora_api.main import app
from catora_api.schemas.recommendations import RecommendationGenerateRequest


class ScalarRows:
    def __init__(self, values: list[uuid.UUID]) -> None:
        self._values = values

    def all(self) -> list[uuid.UUID]:
        return self._values


class GenerationSession:
    def __init__(
        self,
        product_id: uuid.UUID,
        source_record_ids: set[uuid.UUID],
    ) -> None:
        self.product_id = product_id
        self.source_record_ids = source_record_ids
        self.added: list[object] = []
        self.commit_count = 0

    async def scalar(self, _statement: object) -> uuid.UUID:
        return self.product_id

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows(sorted(self.source_record_ids, key=str))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        now = datetime.now(UTC)
        for value in self.added:
            if isinstance(value, Recommendation | RecommendationField):
                if value.id is None:
                    value.id = uuid.uuid4()
                value.created_at = now
                value.updated_at = now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _value: object) -> None:
        return None


class MissingEvidenceSession:
    def __init__(self, product_id: uuid.UUID) -> None:
        self.product_id = product_id

    async def scalar(self, _statement: object) -> uuid.UUID:
        return self.product_id

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows([])


class TargetSession:
    async def scalar(self, _statement: object) -> None:
        return None


class CountingProvider:
    provider_name = "counting"
    model_name = "counting-v1"

    def __init__(self) -> None:
        self.generate_calls = 0

    def estimate_cost_microunits(self, _request: ProviderRequest) -> int:
        return 1

    async def generate(self, _request: ProviderRequest) -> ProviderResponse:
        self.generate_calls += 1
        raise AssertionError("provider should not run for invalid targets")


class FakeAuthService:
    def __init__(self, role: str) -> None:
        self.role = role
        self.calls = 0

    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> object:
        self.calls += 1
        return SimpleNamespace(role=self.role)


def _source() -> SourceDocument:
    return SourceDocument(
        source_record_id=uuid.uuid4(),
        field_path="product.structured.width",
        content="Width: 2100 mm",
        kind="structured_field",
    )


def _request() -> EnrichmentRequest:
    return EnrichmentRequest(
        workspace_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        task_type="normalize_attributes",
        allowed_fields=("width_mm",),
        original_values={"width_mm": 2100},
        sources=(_source(),),
    )


def _payload() -> RecommendationGenerateRequest:
    request = _request()
    return RecommendationGenerateRequest(
        product_id=request.product_id,
        task_type=request.task_type,
        allowed_fields=request.allowed_fields,
        original_values=request.original_values,
        sources=request.sources,
        brand_controls=BrandControls(),
    )


def _context() -> object:
    return SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_mock_provider_runs_through_gateway_deterministically() -> None:
    request = _request()
    result = await EnrichmentGateway(
        DeterministicMockProvider(),
        budget_microunits=100,
        concurrency_limit=1,
        max_attempts=1,
    ).run(request)

    assert result.provider_name == "mock"
    assert result.model_name == "deterministic-catalog-v1"
    assert result.cost_microunits == 100
    assert result.candidates[0].field_key == "width_mm"
    assert result.candidates[0].proposed_value == 2100
    assert result.candidates[0].confidence == "high"
    assert result.candidates[0].requires_verification is False


@pytest.mark.asyncio
async def test_generation_endpoint_runs_mock_gateway_and_persists_version() -> None:
    payload = _payload()
    workspace_id = uuid.uuid4()
    session = GenerationSession(
        payload.product_id,
        {source.source_record_id for source in payload.sources},
    )
    auth_service = FakeAuthService("analyst")

    response = await generate_recommendation(
        workspace_id,
        payload,
        cast(AsyncSession, session),
        cast(AuthService, auth_service),
        Settings(
            environment="test",
            enrichment_provider="mock",
            enrichment_max_run_budget_microunits=100,
        ),
        cast(AuthContext, _context()),
    )

    assert response.workspace_id == workspace_id
    assert response.product_id == payload.product_id
    assert response.model_provider == "mock"
    assert response.cost_microunits == 100
    assert response.fields[0].field_key == "width_mm"
    assert session.commit_count == 1
    assert len([item for item in session.added if isinstance(item, Recommendation)]) == 1
    assert len([item for item in session.added if isinstance(item, AuditEvent)]) == 1


@pytest.mark.asyncio
async def test_invalid_target_is_rejected_before_provider_call() -> None:
    request = _request()
    provider = CountingProvider()

    with pytest.raises(RecommendationTargetError, match="target not found"):
        await RecommendationGenerationService().generate(
            cast(AsyncSession, TargetSession()),
            request=request,
            provider=provider,
            budget_microunits=100,
            concurrency_limit=1,
            max_attempts=1,
            max_output_tokens=100,
        )

    assert provider.generate_calls == 0


@pytest.mark.asyncio
async def test_unrelated_evidence_is_rejected_before_provider_call() -> None:
    request = _request()
    provider = CountingProvider()

    with pytest.raises(RecommendationTargetError, match="evidence not found"):
        await RecommendationGenerationService().generate(
            cast(AsyncSession, MissingEvidenceSession(request.product_id)),
            request=request,
            provider=provider,
            budget_microunits=100,
            concurrency_limit=1,
            max_attempts=1,
            max_output_tokens=100,
        )

    assert provider.generate_calls == 0


@pytest.mark.asyncio
async def test_generation_endpoint_requires_configured_provider() -> None:
    workspace_id = uuid.uuid4()
    auth_service = FakeAuthService("analyst")

    with pytest.raises(HTTPException) as exc_info:
        await generate_recommendation(
            workspace_id,
            _payload(),
            cast(AsyncSession, TargetSession()),
            cast(AuthService, auth_service),
            Settings(environment="test", enrichment_provider="disabled"),
            cast(AuthContext, _context()),
        )

    assert exc_info.value.status_code == 503
    assert auth_service.calls == 1


@pytest.mark.asyncio
async def test_generation_endpoint_requires_write_capability() -> None:
    auth_service = FakeAuthService("viewer")

    with pytest.raises(AuthorizationError, match="generation permission"):
        await generate_recommendation(
            uuid.uuid4(),
            _payload(),
            cast(AsyncSession, TargetSession()),
            cast(AuthService, auth_service),
            Settings(environment="test", enrichment_provider="mock"),
            cast(AuthContext, _context()),
        )

    assert auth_service.calls == 1


def test_mock_provider_is_disabled_in_production() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://production/database",
        s3_secret_key="production-object-storage-secret",
        auth_token_pepper="p" * 40,
        enrichment_provider="mock",
    )

    with pytest.raises(ValueError, match="not allowed in production"):
        settings.validate_production()
    assert configured_provider(provider_name="mock", environment="production") is None


def test_generation_request_rejects_duplicate_fields() -> None:
    request = _request()

    with pytest.raises(ValidationError, match="allowed_fields must be unique"):
        RecommendationGenerateRequest(
            product_id=request.product_id,
            task_type=request.task_type,
            allowed_fields=("width_mm", "width_mm"),
            original_values=request.original_values,
            sources=request.sources,
        )


def test_generation_endpoint_exposes_controlled_contract() -> None:
    path = "/api/v1/workspaces/{workspace_id}/recommendations"
    operation = app.openapi()["paths"][path]["post"]

    assert operation["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RecommendationView")
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/RecommendationGenerateRequest")
