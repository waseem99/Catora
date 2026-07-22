from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import RecommendationJob
from catora_api.enrichment.errors import EnrichmentGatewayError
from catora_api.enrichment.execution import (
    RecommendationGenerationService,
    RecommendationProviderError,
    RecommendationTargetError,
)
from catora_api.enrichment.policies import WorkspaceEnrichmentPolicyService
from catora_api.enrichment.prompts import redact_sensitive_text
from catora_api.enrichment.provider_factory import configured_provider
from catora_api.enrichment.types import EnrichmentRequest, SourceDocument


class RecommendationJobError(RuntimeError):
    pass


class RecommendationJobConfigurationError(RecommendationJobError):
    pass


class RecommendationJobStateError(RecommendationJobError):
    pass


class RecommendationJobService:
    def __init__(self) -> None:
        self._generation = RecommendationGenerationService()
        self._policies = WorkspaceEnrichmentPolicyService()

    async def create(
        self,
        session: AsyncSession,
        *,
        request: EnrichmentRequest,
        requested_by_user_id: uuid.UUID,
        provider_name: str,
        budget_microunits: int,
        audit_finding_id: uuid.UUID | None = None,
    ) -> RecommendationJob:
        effective_request, effective_budget = await self._policies.apply(
            session,
            request=request,
            max_run_budget_microunits=budget_microunits,
        )
        safe_request = sanitized_request(effective_request)
        job = RecommendationJob(
            workspace_id=effective_request.workspace_id,
            requested_by_user_id=requested_by_user_id,
            product_id=effective_request.product_id,
            variant_id=effective_request.variant_id,
            audit_finding_id=audit_finding_id,
            recommendation_id=None,
            status="queued",
            provider_name=provider_name,
            task_type=effective_request.task_type,
            budget_microunits=effective_budget,
            request_snapshot=safe_request.model_dump(mode="json"),
            failure_summary={},
        )
        session.add(job)
        await session.flush()
        if job.id is None:
            raise RecommendationJobStateError(
                "recommendation job identifier was not assigned"
            )
        return job

    async def execute(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        settings: Settings,
    ) -> RecommendationJob | None:
        job = await session.scalar(
            select(RecommendationJob)
            .where(RecommendationJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            return None
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        if job.status != "queued":
            raise RecommendationJobStateError(
                f"Recommendation job {job.id} is already {job.status}"
            )

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.failure_summary = {}
        await session.commit()

        try:
            request = EnrichmentRequest.model_validate(job.request_snapshot)
            if job.provider_name != settings.enrichment_provider:
                raise RecommendationJobConfigurationError(
                    "Enrichment provider configuration changed"
                )
            provider = configured_provider(
                provider_name=job.provider_name,
                environment=settings.environment,
            )
            if provider is None:
                raise RecommendationJobConfigurationError(
                    "Enrichment provider is not configured"
                )
            persisted = await self._generation.generate(
                session,
                request=request,
                provider=provider,
                budget_microunits=job.budget_microunits,
                concurrency_limit=settings.enrichment_concurrency_limit,
                max_attempts=settings.enrichment_max_attempts,
                max_output_tokens=settings.enrichment_max_output_tokens,
                audit_finding_id=job.audit_finding_id,
            )
            job.recommendation_id = persisted.recommendation.id
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.failure_summary = {}
            session.add(
                AuditEvent(
                    workspace_id=job.workspace_id,
                    actor_user_id=job.requested_by_user_id,
                    event_type="recommendation.job_completed",
                    entity_type="recommendation_job",
                    entity_id=job.id,
                    payload={
                        "recommendation_id": str(persisted.recommendation.id),
                        "product_id": str(job.product_id),
                        "task_type": job.task_type,
                        "provider": persisted.recommendation.model_provider,
                        "model": persisted.recommendation.model_name,
                        "cost_microunits": persisted.recommendation.cost_microunits,
                        "field_count": len(persisted.fields),
                    },
                )
            )
            await session.commit()
            return job
        except Exception as exc:
            await session.rollback()
            failed_job = await session.get(RecommendationJob, job_id)
            if failed_job is None:
                raise
            failed_job.status = "failed"
            failed_job.completed_at = datetime.now(UTC)
            failed_job.failure_summary = _failure_summary(exc)
            session.add(
                AuditEvent(
                    workspace_id=failed_job.workspace_id,
                    actor_user_id=failed_job.requested_by_user_id,
                    event_type="recommendation.job_failed",
                    entity_type="recommendation_job",
                    entity_id=failed_job.id,
                    payload=dict(failed_job.failure_summary),
                )
            )
            await session.commit()
            raise


def sanitized_request(request: EnrichmentRequest) -> EnrichmentRequest:
    sources = tuple(
        SourceDocument(
            source_record_id=source.source_record_id,
            field_path=source.field_path,
            content=redact_sensitive_text(source.content),
            checksum=source.checksum,
            kind=source.kind,
        )
        for source in request.sources
    )
    return request.model_copy(update={"sources": sources})


def _failure_summary(exc: Exception) -> dict[str, object]:
    if isinstance(exc, RecommendationTargetError | RecommendationJobConfigurationError):
        message = str(exc)
    elif isinstance(exc, ValidationError):
        message = "Persisted recommendation request is invalid"
    elif isinstance(exc, EnrichmentGatewayError | RecommendationProviderError):
        message = "Recommendation provider execution failed"
    else:
        message = "Recommendation generation failed"
    return {
        "error_type": type(exc).__name__,
        "error_message": message[:500],
    }
