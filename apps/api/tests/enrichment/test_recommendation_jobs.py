from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import (
    Recommendation,
    RecommendationJob,
    WorkspaceEnrichmentPolicy,
)
from catora_api.enrichment.jobs import (
    RecommendationJobConfigurationError,
    RecommendationJobService,
    sanitized_request,
)
from catora_api.enrichment.persistence import PersistedRecommendation
from catora_api.enrichment.types import (
    BrandControls,
    EnrichmentRequest,
    SourceDocument,
)
from catora_api.main import app
from catora_api.schemas.recommendations import (
    RecommendationJobListResponse,
    RecommendationJobView,
)
from catora_api.worker import celery_app


class CreateSession:
    def __init__(self, policy: WorkspaceEnrichmentPolicy | None = None) -> None:
        self.policy = policy
        self.added: list[object] = []
        self.flush_count = 0

    async def scalar(self, _statement: object) -> WorkspaceEnrichmentPolicy | None:
        return self.policy

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        for value in self.added:
            if isinstance(value, RecommendationJob) and value.id is None:
                value.id = uuid.uuid4()


class ExecuteSession:
    def __init__(self, job: RecommendationJob) -> None:
        self.job = job
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    async def scalar(self, _statement: object) -> RecommendationJob:
        return self.job

    async def get(self, _model: object, _identifier: uuid.UUID) -> RecommendationJob:
        return self.job

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class SuccessfulGeneration:
    async def generate(self, _session: object, **_kwargs: object) -> PersistedRecommendation:
        recommendation = Recommendation(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            status="draft",
            task_type="normalize_attributes",
            model_provider="mock",
            model_name="deterministic-catalog-v1",
            prompt_version="enrichment-gateway-v1",
            cost_microunits=100,
            source_snapshot_hash="a" * 64,
            execution_metadata={},
        )
        return PersistedRecommendation(recommendation=recommendation, fields=())


class FailingGeneration:
    async def generate(self, _session: object, **_kwargs: object) -> None:
        raise RuntimeError("sensitive provider detail")


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
                field_path="product.description",
                content="Contact buyer@example.com or use token ghp_12345678901234567890",
                kind="source_copy",
            ),
        ),
    )


def _policy(request: EnrichmentRequest) -> WorkspaceEnrichmentPolicy:
    now = datetime.now(UTC)
    return WorkspaceEnrichmentPolicy(
        id=uuid.uuid4(),
        workspace_id=request.workspace_id,
        brand_controls=BrandControls(
            tone="formal and factual",
            locked_fields=("warranty_months",),
            maximum_lengths={"title": 80},
        ).model_dump(mode="json"),
        max_run_budget_microunits=50,
        created_at=now,
        updated_at=now,
    )


def _job(request: EnrichmentRequest) -> RecommendationJob:
    now = datetime.now(UTC)
    return RecommendationJob(
        id=uuid.uuid4(),
        workspace_id=request.workspace_id,
        requested_by_user_id=uuid.uuid4(),
        product_id=request.product_id,
        variant_id=request.variant_id,
        audit_finding_id=None,
        recommendation_id=None,
        status="queued",
        provider_name="mock",
        task_type=request.task_type,
        budget_microunits=100,
        request_snapshot=sanitized_request(request).model_dump(mode="json"),
        failure_summary={},
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_persists_redacted_request_snapshot() -> None:
    request = _request()
    session = CreateSession()

    job = await RecommendationJobService().create(
        cast(Any, session),
        request=request,
        requested_by_user_id=uuid.uuid4(),
        provider_name="mock",
        budget_microunits=100,
    )

    source = cast(list[dict[str, object]], job.request_snapshot["sources"])[0]
    assert source["content"] == (
        "Contact [REDACTED_EMAIL] or use [REDACTED_SECRET]"
    )
    assert session.added == [job]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_create_persists_effective_workspace_policy() -> None:
    request = _request().model_copy(
        update={
            "brand_controls": BrandControls(
                tone="casual",
                locked_fields=("materials",),
                maximum_lengths={"title": 120},
            )
        }
    )
    session = CreateSession(_policy(request))

    job = await RecommendationJobService().create(
        cast(Any, session),
        request=request,
        requested_by_user_id=uuid.uuid4(),
        provider_name="mock",
        budget_microunits=100,
    )
    snapshot = EnrichmentRequest.model_validate(job.request_snapshot)

    assert job.budget_microunits == 50
    assert snapshot.brand_controls.tone == "formal and factual"
    assert snapshot.brand_controls.locked_fields == (
        "warranty_months",
        "materials",
    )
    assert snapshot.brand_controls.maximum_lengths["title"] == 80


@pytest.mark.asyncio
async def test_execute_completes_job_and_links_recommendation_atomically() -> None:
    request = _request()
    job = _job(request)
    session = ExecuteSession(job)
    service = RecommendationJobService()
    service._generation = cast(Any, SuccessfulGeneration())

    completed = await service.execute(
        cast(Any, session),
        job_id=job.id,
        settings=Settings(environment="test", enrichment_provider="mock"),
    )

    assert completed is job
    assert job.status == "completed"
    assert job.recommendation_id is not None
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.failure_summary == {}
    assert session.commit_count == 2
    assert session.rollback_count == 0
    events = [item for item in session.added if isinstance(item, AuditEvent)]
    assert [event.event_type for event in events] == ["recommendation.job_completed"]


@pytest.mark.asyncio
async def test_execute_rolls_back_partial_work_and_records_safe_failure() -> None:
    request = _request()
    job = _job(request)
    session = ExecuteSession(job)
    service = RecommendationJobService()
    service._generation = cast(Any, FailingGeneration())

    with pytest.raises(RuntimeError, match="sensitive provider detail"):
        await service.execute(
            cast(Any, session),
            job_id=job.id,
            settings=Settings(environment="test", enrichment_provider="mock"),
        )

    assert job.status == "failed"
    assert job.recommendation_id is None
    assert job.failure_summary == {
        "error_type": "RuntimeError",
        "error_message": "Recommendation generation failed",
    }
    assert session.commit_count == 2
    assert session.rollback_count == 1
    events = [item for item in session.added if isinstance(item, AuditEvent)]
    assert [event.event_type for event in events] == ["recommendation.job_failed"]


@pytest.mark.asyncio
async def test_execute_fails_closed_when_provider_configuration_changes() -> None:
    request = _request()
    job = _job(request)
    session = ExecuteSession(job)

    with pytest.raises(RecommendationJobConfigurationError, match="configuration changed"):
        await RecommendationJobService().execute(
            cast(Any, session),
            job_id=job.id,
            settings=Settings(environment="test", enrichment_provider="disabled"),
        )

    assert job.status == "failed"
    assert job.failure_summary["error_type"] == "RecommendationJobConfigurationError"


def test_job_model_indexes_match_query_contract() -> None:
    index = next(
        item
        for item in RecommendationJob.__table__.indexes
        if item.name == "ix_recommendation_jobs_workspace_status_created"
    )
    assert [column.name for column in index.columns] == [
        "workspace_id",
        "status",
        "created_at",
    ]


def test_job_endpoints_and_responses_are_registered() -> None:
    collection = "/api/v1/workspaces/{workspace_id}/recommendation-jobs"
    detail = collection + "/{job_id}"
    paths = app.openapi()["paths"]

    assert paths[collection]["post"]["responses"]["202"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/RecommendationJobView")
    assert paths[collection]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/RecommendationJobListResponse")
    assert paths[detail]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/RecommendationJobView")
    assert "request_snapshot" not in RecommendationJobView.model_fields
    assert set(RecommendationJobListResponse.model_fields) == {
        "items",
        "total",
        "offset",
        "limit",
    }


def test_worker_registers_recommendation_task_module() -> None:
    assert "catora_api.enrichment.tasks" in celery_app.conf.imports
