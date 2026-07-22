from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from catora_api.auth.dependencies import (
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import RecommendationJob
from catora_api.enrichment.jobs import (
    RecommendationJobConfigurationError,
    RecommendationJobService,
    RecommendationJobStateError,
)
from catora_api.enrichment.provider_factory import configured_provider
from catora_api.schemas.recommendations import RecommendationJobView
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["recommendation jobs"])
job_service = RecommendationJobService()


def _require_recommendation_write(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Recommendation generation permission required")


async def _job(
    session: SessionDependency,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> RecommendationJob:
    job = await job_service.get(
        session,
        workspace_id=workspace_id,
        job_id=job_id,
        for_update=True,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Recommendation job not found")
    return job


@router.post(
    "/workspaces/{workspace_id}/recommendation-jobs/{job_id}/cancel",
    response_model=RecommendationJobView,
)
async def cancel_recommendation_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> RecommendationJobView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_recommendation_write(membership.role)
    job = await _job(session, workspace_id=workspace_id, job_id=job_id)
    if job.status == "cancelled":
        return RecommendationJobView.model_validate(job)
    try:
        await job_service.cancel(session, job=job)
    except RecommendationJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="recommendation.job_cancelled",
            entity_type="recommendation_job",
            entity_id=job.id,
            payload={
                "product_id": str(job.product_id),
                "retry_count": job.retry_count,
            },
        )
    )
    await session.commit()
    await session.refresh(job)
    return RecommendationJobView.model_validate(job)


@router.post(
    "/workspaces/{workspace_id}/recommendation-jobs/{job_id}/retry",
    response_model=RecommendationJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_recommendation_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    settings: SettingsDependency,
    context: CsrfContextDependency,
) -> RecommendationJobView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_recommendation_write(membership.role)
    if (
        configured_provider(
            provider_name=settings.enrichment_provider,
            environment=settings.environment,
        )
        is None
    ):
        raise HTTPException(status_code=503, detail="Enrichment provider is not configured")
    source_job = await _job(session, workspace_id=workspace_id, job_id=job_id)
    try:
        retry_job = await job_service.retry(
            session,
            source_job=source_job,
            requested_by_user_id=context.user.id,
            provider_name=settings.enrichment_provider,
            max_retries=settings.enrichment_max_job_retries,
            max_run_budget_microunits=(
                settings.enrichment_max_run_budget_microunits
            ),
        )
    except RecommendationJobConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecommendationJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="recommendation.job_retried",
            entity_type="recommendation_job",
            entity_id=retry_job.id,
            payload={
                "retry_of_job_id": str(source_job.id),
                "retry_count": retry_job.retry_count,
                "provider": retry_job.provider_name,
                "budget_microunits": retry_job.budget_microunits,
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task("catora.recommendation.run", args=[str(retry_job.id)])
    except Exception as exc:
        retry_job.status = "failed"
        retry_job.completed_at = datetime.now(UTC)
        retry_job.failure_summary = {
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue recommendation job",
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=context.user.id,
                event_type="recommendation.job_enqueue_failed",
                entity_type="recommendation_job",
                entity_id=retry_job.id,
                payload=dict(retry_job.failure_summary),
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Unable to enqueue recommendation job",
        ) from exc
    await session.refresh(retry_job)
    return RecommendationJobView.model_validate(retry_job)
