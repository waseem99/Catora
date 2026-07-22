from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from catora_api.api.recommendation_usage import get_recommendation_usage
from catora_api.auth.service import AuthContext, AuthService
from catora_api.main import app
from catora_api.schemas.recommendation_usage import RecommendationUsageReport


class Result:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def one(self) -> tuple[object, ...]:
        assert len(self.rows) == 1
        return self.rows[0]

    def all(self) -> list[tuple[object, ...]]:
        return self.rows


class UsageSession:
    def __init__(self, results: list[Result]) -> None:
        self.results = results
        self.execute_count = 0

    async def execute(self, _statement: object) -> Result:
        result = self.results[self.execute_count]
        self.execute_count += 1
        return result


class FakeAuthService:
    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> object:
        return SimpleNamespace(role="viewer")


def _context() -> object:
    return SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_usage_report_reconciles_cost_jobs_and_breakdowns() -> None:
    workspace_id = uuid.uuid4()
    session = UsageSession(
        [
            Result([(3, 1_250)]),
            Result([("mock", "mock-v1", 2, 750), ("openai", "gpt-x", 1, 500)]),
            Result([("improve_title", 2, 750), ("normalize_attributes", 1, 500)]),
            Result(
                [
                    ("completed", 2, 0, 0),
                    ("failed", 1, 1, 0),
                    ("queued", 1, 2, 900),
                    ("running", 1, 0, 600),
                ]
            ),
        ]
    )

    report = await get_recommendation_usage(
        workspace_id,
        cast(Any, session),
        cast(AuthService, FakeAuthService()),
        cast(AuthContext, _context()),
    )

    assert report.recommendations.recommendation_count == 3
    assert report.recommendations.total_cost_microunits == 1_250
    assert report.jobs.total == 5
    assert report.jobs.completed == 2
    assert report.jobs.failed == 1
    assert report.jobs.queued == 1
    assert report.jobs.running == 1
    assert report.jobs.cancelled == 0
    assert report.jobs.retry_count == 3
    assert report.jobs.active_budget_microunits == 1_500
    assert [item.provider_name for item in report.providers] == ["mock", "openai"]
    assert [item.task_type for item in report.tasks] == [
        "improve_title",
        "normalize_attributes",
    ]
    assert session.execute_count == 4


@pytest.mark.asyncio
async def test_usage_report_rejects_inverted_time_range_before_queries() -> None:
    now = datetime.now(UTC)
    session = UsageSession([])

    with pytest.raises(HTTPException, match="created_to") as exc_info:
        await get_recommendation_usage(
            uuid.uuid4(),
            cast(Any, session),
            cast(AuthService, FakeAuthService()),
            cast(AuthContext, _context()),
            created_from=now,
            created_to=now - timedelta(seconds=1),
        )

    assert exc_info.value.status_code == 422
    assert session.execute_count == 0


def test_usage_api_contract_is_registered() -> None:
    path = "/api/v1/workspaces/{workspace_id}/recommendation-usage"
    operation = app.openapi()["paths"][path]["get"]
    parameter_names = {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter["in"] in {"path", "query"}
    }

    assert parameter_names == {"workspace_id", "created_from", "created_to"}
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/RecommendationUsageReport")
    assert set(RecommendationUsageReport.model_fields) == {
        "workspace_id",
        "created_from",
        "created_to",
        "recommendations",
        "jobs",
        "providers",
        "tasks",
    }
