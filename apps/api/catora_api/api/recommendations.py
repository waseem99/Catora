from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import (
    Recommendation,
    RecommendationField,
    RecommendationJob,
)
from catora_api.enrichment.errors import BudgetExceededError, EnrichmentGatewayError
from catora_api.enrichment.execution import (
    RecommendationGenerationService,
    RecommendationProviderError,
    RecommendationTargetError,
)
from catora_api.enrichment.jobs import RecommendationJobService
from catora_api.enrichment.provider import ProviderAdapter
from catora_api.enrichment.provider_factory import configured_provider
from catora_api.enrichment.types import EnrichmentTask
from catora_api.schemas.recommendations import (
    RecommendationFieldView,
    RecommendationGenerateRequest,
    RecommendationJobListResponse,
    RecommendationJobStatus,
    RecommendationJobView,
    RecommendationListResponse,
    RecommendationView,
)
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["recommendations"])
generation_service = RecommendationGenerationService()
job_service = RecommendationJobService()


def _require_recommendation_write(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Recommendation generation permission required")


async def _fields_by_recommendation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    recommendation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[RecommendationField]]:
    if not recommendation_ids:
        return {}
    fields = (
        await session.scalars(
            select(RecommendationField)
            .where(
                RecommendationField.workspace_id == workspace_id,
                RecommendationField.recommendation_id.in_(recommendation_ids),
            )
            .order_by(
                RecommendationField.recommendation_id,
                RecommendationField.field_key,
                RecommendationField.id,
            )
        )
    ).all()
    grouped: defaultdict[uuid.UUID, list[RecommendationField]] = defaultdict(list)
    for field in fields:
        grouped[field.recommendation_id].append(field)
    return dict(grouped)


def _recommendation_view(
    recommendation: Recommendation,
    fields: list[RecommendationField],
) -> RecommendationView:
    return RecommendationView(
        id=recommendation.id,
        workspace_id=cast(uuid.UUID, recommendation.workspace_id),
        product_id=recommendation.product_id,
        variant_id=recommendation.variant_id,
        audit_finding_id=recommendation.audit_finding_id,
        status=recommendation.status,
        task_type=cast(EnrichmentTask, recommendation.task_type),
        model_provider=recommendation.model_provider,
        model_name=recommendation.model_name,
        prompt_version=recommendation.prompt_version,
        cost_microunits=recommendation.cost_microunits,
        source_snapshot_hash=recommendation.source_snapshot_hash,
        execution_metadata=recommendation.execution_metadata,
        fields=[RecommendationFieldView.model_validate(field) for field in fields],
        created_at=recommendation.created_at,
        updated_at=recommendation.updated_at,
    )


def _budget(
    payload: RecommendationGenerateRequest,
    configured_maximum: int,
) -> int:
    requested = payload.budget_microunits or configured_maximum
    if requested > configured_maximum:
        raise HTTPException(
            status_code=422,
            detail="Requested enrichment budget exceeds the configured maximum",
        )
    return requested


def _provider(
    *,
    provider_name: str,
    environment: str,
) -> ProviderAdapter:
    provider = configured_provider(
        provider_name=provider_name,
        environment=environment,
    )
    if provider is None:
        raise HTTPException(status_code=503, detail="Enrichment provider is not configured")
    return provider


@router.post(
    "/workspaces/{workspace_id}/recommendations",
    response_model=RecommendationView,
    status_code=status.HTTP_201_CREATED,
)
async def generate_recommendation(
    workspace_id: uuid.UUID,
    payload: RecommendationGenerateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    settings: SettingsDependency,
    context: CsrfContextDependency,
) -> RecommendationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_recommendation_write(membership.role)
    provider = _provider(
        provider_name=settings.enrichment_provider,
        environment=settings.environment,
    )
    budget_microunits = _budget(
        payload,
        settings.enrichment_max_run_budget_microunits,
    )

    request = payload.enrichment_request(workspace_id)
    try:
        persisted = await generation_service.generate(
            session,
            request=request,
            provider=provider,
            budget_microunits=budget_microunits,
            concurrency_limit=settings.enrichment_concurrency_limit,
            max_attempts=settings.enrichment_max_attempts,
            max_output_tokens=settings.enrichment_max_output_tokens,
            audit_finding_id=payload.audit_finding_id,
        )
    except RecommendationTargetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EnrichmentGatewayError as exc:
        raise HTTPException(
            status_code=502,
            detail="Enrichment provider output was invalid",
        ) from exc
    except RecommendationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    recommendation = persisted.recommendation
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="recommendation.generated",
            entity_type="recommendation",
            entity_id=recommendation.id,
            payload={
                "product_id": str(recommendation.product_id),
                "variant_id": (
                    str(recommendation.variant_id)
                    if recommendation.variant_id is not None
                    else None
                ),
                "audit_finding_id": (
                    str(recommendation.audit_finding_id)
                    if recommendation.audit_finding_id is not None
                    else None
                ),
                "task_type": recommendation.task_type,
                "provider": recommendation.model_provider,
                "model": recommendation.model_name,
                "prompt_version": recommendation.prompt_version,
                "cost_microunits": recommendation.cost_microunits,
                "field_count": len(persisted.fields),
            },
        )
    )
    await session.commit()
    await session.refresh(recommendation)
    for field in persisted.fields:
        await session.refresh(field)
    return _recommendation_view(recommendation, list(persisted.fields))


@router.post(
    "/workspaces/{workspace_id}/recommendation-jobs",
    response_model=RecommendationJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_recommendation_job(
    workspace_id: uuid.UUID,
    payload: RecommendationGenerateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    settings: SettingsDependency,
    context: CsrfContextDependency,
) -> RecommendationJobView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_recommendation_write(membership.role)
    _provider(
        provider_name=settings.enrichment_provider,
        environment=settings.environment,
    )
    budget_microunits = _budget(
        payload,
        settings.enrichment_max_run_budget_microunits,
    )
    job = await job_service.create(
        session,
        request=payload.enrichment_request(workspace_id),
        requested_by_user_id=context.user.id,
        provider_name=settings.enrichment_provider,
        budget_microunits=budget_microunits,
        audit_finding_id=payload.audit_finding_id,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="recommendation.job_queued",
            entity_type="recommendation_job",
            entity_id=job.id,
            payload={
                "product_id": str(job.product_id),
                "variant_id": str(job.variant_id) if job.variant_id is not None else None,
                "audit_finding_id": (
                    str(job.audit_finding_id)
                    if job.audit_finding_id is not None
                    else None
                ),
                "task_type": job.task_type,
                "provider": job.provider_name,
                "budget_microunits": job.budget_microunits,
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task("catora.recommendation.run", args=[str(job.id)])
    except Exception as exc:
        job.status = "failed"
        job.completed_at = datetime.now(UTC)
        job.failure_summary = {
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue recommendation job",
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=context.user.id,
                event_type="recommendation.job_enqueue_failed",
                entity_type="recommendation_job",
                entity_id=job.id,
                payload=dict(job.failure_summary),
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Unable to enqueue recommendation job",
        ) from exc
    await session.refresh(job)
    return RecommendationJobView.model_validate(job)


@router.get(
    "/workspaces/{workspace_id}/recommendation-jobs",
    response_model=RecommendationJobListResponse,
)
async def list_recommendation_jobs(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    job_status: Annotated[
        RecommendationJobStatus | None,
        Query(alias="status"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RecommendationJobListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    query = select(RecommendationJob).where(
        RecommendationJob.workspace_id == workspace_id
    )
    if product_id is not None:
        query = query.where(RecommendationJob.product_id == product_id)
    if job_status is not None:
        query = query.where(RecommendationJob.status == job_status)
    total = int(
        (
            await session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
        )
        or 0
    )
    jobs = (
        await session.scalars(
            query.order_by(RecommendationJob.created_at.desc(), RecommendationJob.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return RecommendationJobListResponse(
        items=[RecommendationJobView.model_validate(job) for job in jobs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/workspaces/{workspace_id}/recommendation-jobs/{job_id}",
    response_model=RecommendationJobView,
)
async def get_recommendation_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> RecommendationJobView:
    await auth_service.membership(session, context.user.id, workspace_id)
    job = await session.scalar(
        select(RecommendationJob).where(
            RecommendationJob.id == job_id,
            RecommendationJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Recommendation job not found")
    return RecommendationJobView.model_validate(job)


@router.get(
    "/workspaces/{workspace_id}/recommendations",
    response_model=RecommendationListResponse,
)
async def list_recommendations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", min_length=1, max_length=30),
    ] = None,
    task_type: Annotated[EnrichmentTask | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RecommendationListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    query = select(Recommendation).where(Recommendation.workspace_id == workspace_id)
    if product_id is not None:
        query = query.where(Recommendation.product_id == product_id)
    if status_filter is not None:
        query = query.where(Recommendation.status == status_filter)
    if task_type is not None:
        query = query.where(Recommendation.task_type == task_type)

    total = int(
        (
            await session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
        )
        or 0
    )
    recommendations = (
        await session.scalars(
            query.order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    fields_by_recommendation = await _fields_by_recommendation(
        session,
        workspace_id=workspace_id,
        recommendation_ids=[item.id for item in recommendations],
    )
    return RecommendationListResponse(
        items=[
            _recommendation_view(item, fields_by_recommendation.get(item.id, []))
            for item in recommendations
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/workspaces/{workspace_id}/recommendations/{recommendation_id}",
    response_model=RecommendationView,
)
async def get_recommendation(
    workspace_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> RecommendationView:
    await auth_service.membership(session, context.user.id, workspace_id)
    recommendation = await session.scalar(
        select(Recommendation).where(
            Recommendation.id == recommendation_id,
            Recommendation.workspace_id == workspace_id,
        )
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    fields_by_recommendation = await _fields_by_recommendation(
        session,
        workspace_id=workspace_id,
        recommendation_ids=[recommendation.id],
    )
    return _recommendation_view(
        recommendation,
        fields_by_recommendation.get(recommendation.id, []),
    )
