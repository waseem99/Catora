from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models.workflow import RecommendationJob
from catora_api.enrichment.jobs import (
    RecommendationJobService,
    RecommendationJobStateError,
    sanitized_request,
)
from catora_api.enrichment.types import EnrichmentRequest, SourceDocument
from catora_api.main import app
from catora_api.schemas.recommendations import RecommendationJobView


class ActionSession:
    def __init__(self, scalar_values: list[object | None] | None = None) -> None:
        self.scalar_values = list(scalar_values or [])
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        for value in self.added:
            if isinstance(value, RecommendationJob) and value.id is None:
                value.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_count += 1


class ExecuteSession:
    def __init__(self, job: RecommendationJob) -> None:
        self.job = job
        self.commit_count = 0

    async def scalar(self, _statement: object) -> RecommendationJob:
        return self.job

    async def commit(self) -> None:
        self.commit_count += 1


def _request() -> EnrichmentRequest:
    return EnrichmentRequest(
        workspace_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        task_type="normalize_attributes",
        allowed_fields=("width_mm",),
        original_values={"width_mm": 2100},
        sources=(
            SourceDocument(
                source_record_id=uuid.uuid4(),
                field_path="product.width",
                content="Width: 2100 mm",
                kind="structured_field",
            ),
        ),
    )


def _job(*, status: str = "failed", retry_count: int = 0) -> RecommendationJob:
    request = _request()
    now = datetime.now(UTC)
    return RecommendationJob(
        id=uuid.uuid4(),
        workspace_id=request.workspace_id,
        requested_by_user_id=uuid.uuid4(),
        product_id=request.product_id,
        variant_id=None,
        audit_finding_id=None,
        recommendation_id=None,
        retry_of_job_id=None,
        retry_count=retry_count,
        status=status,
        provider_name="mock",
        task_type=request.task_type,
        budget_microunits=100,
        request_snapshot=sanitized_request(request).model_dump(mode="json"),
        failure_summary={
            "error_type": "RuntimeError",
            "error_message": "Recommendation generation failed",
        },
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_cancel_marks_only_queued_job_terminal() -> None:
    job = _job(status="queued")
    job.started_at = None
    job.completed_at = None
    session = ActionSession()

    cancelled = await RecommendationJobService().cancel(
        cast(Any, session),
        job=job,
    )

    assert cancelled is job
    assert job.status == "cancelled"
    assert job.completed_at is not None
    assert job.failure_summary == {}
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_cancel_rejects_running_job() -> None:
    with pytest.raises(RecommendationJobStateError, match="Only queued"):
        await RecommendationJobService().cancel(
            cast(Any, ActionSession()),
            job=_job(status="running"),
        )


@pytest.mark.asyncio
async def test_retry_creates_append_only_linked_child() -> None:
    source = _job(status="failed", retry_count=1)
    original_failure = dict(source.failure_summary)
    session = ActionSession([None, None])

    retry = await RecommendationJobService().retry(
        cast(Any, session),
        source_job=source,
        requested_by_user_id=uuid.uuid4(),
        provider_name="mock",
        max_retries=2,
        max_run_budget_microunits=75,
    )

    assert retry.id != source.id
    assert retry.retry_of_job_id == source.id
    assert retry.retry_count == 2
    assert retry.status == "queued"
    assert retry.budget_microunits == 75
    assert source.status == "failed"
    assert source.failure_summary == original_failure


@pytest.mark.asyncio
async def test_retry_limit_and_branching_are_rejected() -> None:
    source = _job(status="failed", retry_count=2)
    with pytest.raises(RecommendationJobStateError, match="retry limit"):
        await RecommendationJobService().retry(
            cast(Any, ActionSession()),
            source_job=source,
            requested_by_user_id=uuid.uuid4(),
            provider_name="mock",
            max_retries=2,
            max_run_budget_microunits=100,
        )

    source.retry_count = 0
    with pytest.raises(RecommendationJobStateError, match="already been retried"):
        await RecommendationJobService().retry(
            cast(Any, ActionSession([uuid.uuid4()])),
            source_job=source,
            requested_by_user_id=uuid.uuid4(),
            provider_name="mock",
            max_retries=2,
            max_run_budget_microunits=100,
        )


@pytest.mark.asyncio
async def test_worker_delivery_is_noop_for_cancelled_job() -> None:
    job = _job(status="cancelled")
    session = ExecuteSession(job)

    result = await RecommendationJobService().execute(
        cast(Any, session),
        job_id=job.id,
        settings=Settings(environment="test", enrichment_provider="mock"),
    )

    assert result is job
    assert session.commit_count == 0


def test_retry_lineage_model_and_response_contract() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in RecommendationJob.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("retry_of_job_id",) in unique_columns
    assert "retry_of_job_id" in RecommendationJobView.model_fields
    assert "retry_count" in RecommendationJobView.model_fields


def test_cancel_and_retry_api_contracts_are_registered() -> None:
    base = "/api/v1/workspaces/{workspace_id}/recommendation-jobs/{job_id}"
    paths = app.openapi()["paths"]

    assert paths[base + "/cancel"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/RecommendationJobView")
    assert paths[base + "/retry"]["post"]["responses"]["202"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/RecommendationJobView")
