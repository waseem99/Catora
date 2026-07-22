from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from catora_api.api.recommendation_usage import get_recommendation_usage
from catora_api.auth.service import AuthContext, AuthService
from catora_api.enrichment.usage import (
    RecommendationUsageRecord,
    _completed_job_count_query,
    _usage_query,
    aggregate_usage,
)
from catora_api.main import app


def test_usage_aggregation_reconciles_tokens_cost_and_providers() -> None:
    summary = aggregate_usage(
        (
            RecommendationUsageRecord(
                provider="alpha",
                model="model-2",
                cost_microunits=200,
                execution_metadata={"input_tokens": 12, "output_tokens": 3},
            ),
            RecommendationUsageRecord(
                provider="alpha",
                model="model-2",
                cost_microunits=100,
                execution_metadata={"input_tokens": "invalid", "output_tokens": -1},
            ),
            RecommendationUsageRecord(
                provider="alpha",
                model="model-1",
                cost_microunits=50,
                execution_metadata={"input_tokens": 4, "output_tokens": 2},
            ),
        ),
        completed_job_count=2,
    )

    assert summary.recommendation_count == 3
    assert summary.completed_job_count == 2
    assert summary.input_tokens == 16
    assert summary.output_tokens == 5
    assert summary.cost_microunits == 350
    assert [(item.provider, item.model) for item in summary.providers] == [
        ("alpha", "model-1"),
        ("alpha", "model-2"),
    ]
    assert summary.providers[1].recommendation_count == 2
    assert summary.providers[1].input_tokens == 12


def test_usage_aggregation_treats_invalid_historical_values_as_zero() -> None:
    summary = aggregate_usage(
        (
            RecommendationUsageRecord(
                provider="mock",
                model="v1",
                cost_microunits=-1,
                execution_metadata={"input_tokens": True, "output_tokens": None},
            ),
        ),
        completed_job_count=-3,
    )

    assert summary.input_tokens == 0
    assert summary.output_tokens == 0
    assert summary.cost_microunits == 0
    assert summary.completed_job_count == 0


def test_usage_queries_apply_tenant_and_product_filters() -> None:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    usage_sql = str(
        _usage_query(
            workspace_id=workspace_id,
            product_id=product_id,
            provider="mock",
            created_from=None,
            created_before=None,
        ).compile(dialect=postgresql.dialect())
    )
    jobs_sql = str(
        _completed_job_count_query(
            workspace_id=workspace_id,
            product_id=product_id,
            provider="mock",
            created_from=None,
            created_before=None,
        ).compile(dialect=postgresql.dialect())
    )

    assert "recommendations.workspace_id" in usage_sql
    assert "recommendations.product_id" in usage_sql
    assert "recommendations.model_provider" in usage_sql
    assert "recommendation_jobs.workspace_id" in jobs_sql
    assert "recommendation_jobs.recommendation_id" in jobs_sql
    assert "recommendation_jobs.status" in jobs_sql


class MissingProductSession:
    async def scalar(self, _statement: object) -> None:
        return None


class MembershipAuth:
    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> object:
        return SimpleNamespace(role="viewer")


@pytest.mark.asyncio
async def test_cross_workspace_product_filter_is_non_disclosing() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_recommendation_usage(
            workspace_id=uuid.uuid4(),
            session=cast(Any, MissingProductSession()),
            auth_service=cast(AuthService, MembershipAuth()),
            context=cast(
                AuthContext,
                SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4())),
            ),
            product_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Product not found"


def test_usage_openapi_contract_is_registered() -> None:
    path = "/api/v1/workspaces/{workspace_id}/recommendation-usage"
    operation = app.openapi()["paths"][path]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RecommendationUsageView")
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "workspace_id",
        "product_id",
        "provider",
        "created_from",
        "created_before",
        "authorization",
    }
