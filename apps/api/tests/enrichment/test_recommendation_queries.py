from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.api.recommendations import get_recommendation, list_recommendations
from catora_api.auth.service import AuthContext, AuthService
from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.main import app
from catora_api.schemas.recommendations import (
    RecommendationFieldView,
    RecommendationListResponse,
    RecommendationView,
)


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class ListSession:
    def __init__(
        self,
        recommendation: Recommendation,
        field: RecommendationField,
    ) -> None:
        self.recommendation = recommendation
        self.field = field
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalar(self, _statement: object) -> object:
        self.scalar_calls += 1
        return 1

    async def scalars(self, _statement: object) -> ScalarRows:
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return ScalarRows([self.recommendation])
        return ScalarRows([self.field])


class DetailSession:
    def __init__(
        self,
        recommendation: Recommendation | None,
        field: RecommendationField | None = None,
    ) -> None:
        self.recommendation = recommendation
        self.field = field
        self.scalars_calls = 0

    async def scalar(self, _statement: object) -> object | None:
        return self.recommendation

    async def scalars(self, _statement: object) -> ScalarRows:
        self.scalars_calls += 1
        return ScalarRows([] if self.field is None else [self.field])


class FakeAuthService:
    def __init__(self) -> None:
        self.membership_calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def membership(
        self,
        _session: object,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> object:
        self.membership_calls.append((user_id, workspace_id))
        return SimpleNamespace(role="analyst")


def _records() -> tuple[Recommendation, RecommendationField]:
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    recommendation_id = uuid.uuid4()
    recommendation = Recommendation(
        id=recommendation_id,
        workspace_id=workspace_id,
        product_id=uuid.uuid4(),
        variant_id=None,
        audit_finding_id=uuid.uuid4(),
        status="draft",
        task_type="normalize_attributes",
        model_provider="mock",
        model_name="deterministic-v1",
        prompt_version="enrichment-gateway-v1",
        cost_microunits=17,
        source_snapshot_hash="a" * 64,
        execution_metadata={
            "request_id": str(uuid.uuid4()),
            "prompt_fingerprint": "b" * 64,
            "attempt_count": 1,
        },
        created_at=now,
        updated_at=now,
    )
    field = RecommendationField(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        recommendation_id=recommendation_id,
        field_key="materials",
        original_value=["oak"],
        proposed_value=["solid oak"],
        edited_value=None,
        evidence=[{"field_path": "structured.materials"}],
        confidence="high",
        requires_verification=False,
        proposal_metadata={
            "claim_type": "fact",
            "inferred": False,
            "evidence_conflict": False,
            "explanation": "Uses explicit source evidence.",
        },
        created_at=now,
        updated_at=now,
    )
    return recommendation, field


def _context(user_id: uuid.UUID) -> object:
    return SimpleNamespace(user=SimpleNamespace(id=user_id))


@pytest.mark.asyncio
async def test_list_returns_reconcilable_total_and_complete_metadata() -> None:
    recommendation, field = _records()
    session = ListSession(recommendation, field)
    auth_service = FakeAuthService()
    user_id = uuid.uuid4()

    response = await list_recommendations(
        recommendation.workspace_id,
        cast(AsyncSession, session),
        cast(AuthService, auth_service),
        cast(AuthContext, _context(user_id)),
        product_id=recommendation.product_id,
        status_filter="draft",
        task_type="normalize_attributes",
        offset=0,
        limit=50,
    )

    assert response.total == 1
    assert response.offset == 0
    assert response.limit == 50
    assert response.items[0].execution_metadata["attempt_count"] == 1
    assert response.items[0].fields[0].proposal_metadata["claim_type"] == "fact"
    assert auth_service.membership_calls == [(user_id, recommendation.workspace_id)]
    assert session.scalar_calls == 1
    assert session.scalars_calls == 2


@pytest.mark.asyncio
async def test_detail_returns_non_disclosing_not_found_after_membership() -> None:
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    auth_service = FakeAuthService()

    with pytest.raises(HTTPException) as exc_info:
        await get_recommendation(
            workspace_id,
            uuid.uuid4(),
            cast(AsyncSession, DetailSession(None)),
            cast(AuthService, auth_service),
            cast(AuthContext, _context(user_id)),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Recommendation not found"
    assert auth_service.membership_calls == [(user_id, workspace_id)]


def test_recommendation_endpoints_expose_stable_query_contracts() -> None:
    list_path = "/api/v1/workspaces/{workspace_id}/recommendations"
    detail_path = "/api/v1/workspaces/{workspace_id}/recommendations/{recommendation_id}"
    schema = app.openapi()
    list_operation = schema["paths"][list_path]["get"]
    detail_operation = schema["paths"][detail_path]["get"]

    assert {
        parameter["name"]
        for parameter in list_operation["parameters"]
        if parameter["in"] in {"path", "query"}
    } == {
        "workspace_id",
        "product_id",
        "status",
        "task_type",
        "offset",
        "limit",
    }
    assert {
        parameter["name"]
        for parameter in detail_operation["parameters"]
        if parameter["in"] == "path"
    } == {"workspace_id", "recommendation_id"}
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RecommendationListResponse")
    assert detail_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RecommendationView")


def test_recommendation_schemas_include_auditable_metadata() -> None:
    assert set(RecommendationListResponse.model_fields) == {
        "items",
        "total",
        "offset",
        "limit",
    }
    assert {
        "execution_metadata",
        "source_snapshot_hash",
        "cost_microunits",
        "fields",
    }.issubset(RecommendationView.model_fields)
    assert {
        "evidence",
        "confidence",
        "requires_verification",
        "proposal_metadata",
    }.issubset(RecommendationFieldView.model_fields)
