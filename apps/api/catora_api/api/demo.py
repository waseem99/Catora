from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, HTTPException, Response, status

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models.reporting import AuditEvent
from catora_api.demo.pptx import build_demo_pptx
from catora_api.demo.reliability import (
    build_preflight,
    demo_reset_status,
    enqueue_demo_reset,
    require_presenter_workspace,
    reset_task_belongs_to_workspace,
)
from catora_api.demo.service import DemoService
from catora_api.schemas.demo import (
    DemoOverviewResponse,
    DemoPreflightResponse,
    DemoRecommendationDecisionRequest,
    DemoRecommendationDecisionResponse,
    DemoResetRequest,
    DemoResetResponse,
    DemoResetStatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["client-demo"])
service = DemoService()


async def _require_presenter(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    user_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(session, user_id, workspace_id)
    if not can(Role(membership.role), "demo.present"):
        raise AuthorizationError("Presenter permission required")
    await require_presenter_workspace(session, workspace_id=workspace_id)


@router.get(
    "/workspaces/{workspace_id}/demo",
    response_model=DemoOverviewResponse,
)
async def get_demo_overview(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> DemoOverviewResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    return await service.overview(session, workspace_id=workspace_id)


@router.get(
    "/workspaces/{workspace_id}/demo/preflight",
    response_model=DemoPreflightResponse,
)
async def get_demo_preflight(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> DemoPreflightResponse:
    await _require_presenter(
        workspace_id,
        session,
        auth_service,
        context.user.id,
    )
    return await build_preflight(
        session,
        workspace_id=workspace_id,
        settings=auth_service.settings,
    )


@router.post(
    "/workspaces/{workspace_id}/demo/reset",
    response_model=DemoResetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_demo_reset(
    workspace_id: uuid.UUID,
    payload: DemoResetRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DemoResetResponse:
    await _require_presenter(
        workspace_id,
        session,
        auth_service,
        context.user.id,
    )
    task_id = uuid.uuid4()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="demo.reset_requested",
            entity_type="workspace",
            entity_id=workspace_id,
            payload={"task_id": str(task_id), "reason": payload.reason},
        )
    )
    await session.commit()
    try:
        enqueue_demo_reset(
            task_id=task_id,
            actor_user_id=context.user.id,
            reason=payload.reason,
        )
    except Exception as exc:
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=context.user.id,
                event_type="demo.reset_enqueue_failed",
                entity_type="workspace",
                entity_id=workspace_id,
                payload={
                    "task_id": str(task_id),
                    "reason": payload.reason,
                    "error_type": type(exc).__name__,
                },
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The demo reset could not be queued",
        ) from exc
    return DemoResetResponse(task_id=task_id, status="queued")


@router.get(
    "/workspaces/{workspace_id}/demo/reset/{task_id}",
    response_model=DemoResetStatusResponse,
)
async def get_demo_reset_status(
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> DemoResetStatusResponse:
    await _require_presenter(
        workspace_id,
        session,
        auth_service,
        context.user.id,
    )
    if not await reset_task_belongs_to_workspace(
        session,
        workspace_id=workspace_id,
        task_id=task_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reset task not found")
    return demo_reset_status(task_id)


@router.post(
    "/workspaces/{workspace_id}/demo/recommendations/{recommendation_id}/decision",
    response_model=DemoRecommendationDecisionResponse,
)
async def decide_demo_recommendation(
    workspace_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    payload: DemoRecommendationDecisionRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DemoRecommendationDecisionResponse:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "recommendations.review"):
        raise AuthorizationError("Recommendation review permission required")
    return await service.decide(
        session,
        workspace_id=workspace_id,
        recommendation_id=recommendation_id,
        reviewer_user_id=context.user.id,
        payload=payload,
    )


@router.get("/workspaces/{workspace_id}/demo/backlog.csv")
async def download_demo_backlog(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Response:
    await auth_service.membership(session, context.user.id, workspace_id)
    overview = await service.overview(session, workspace_id=workspace_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "product_id",
            "product_title",
            "record_type",
            "severity_or_state",
            "field_key",
            "current_value",
            "proposed_or_remediation",
            "evidence",
            "verification_required",
        ]
    )
    for finding in overview.findings:
        evidence = " | ".join(
            str(item.get("excerpt") or item.get("field_path") or item)
            for item in finding.evidence
        )
        writer.writerow(
            [
                finding.product_id,
                finding.product_title,
                "finding",
                finding.severity,
                finding.field_key,
                "",
                finding.remediation_type,
                evidence,
                "",
            ]
        )
    for field in overview.recommendation.fields:
        evidence = " | ".join(
            str(item.get("excerpt") or item.get("field_path") or item)
            for item in field.evidence
        )
        writer.writerow(
            [
                overview.recommendation.product_id,
                overview.recommendation.product_title,
                "recommendation",
                field.decision or overview.recommendation.status,
                field.field_key,
                field.original_value,
                field.edited_value if field.edited_value is not None else field.proposed_value,
                evidence,
                field.requires_verification,
            ]
        )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="demo.backlog_downloaded",
            entity_type="workspace",
            entity_id=workspace_id,
            payload={"row_count": len(overview.findings) + len(overview.recommendation.fields)},
        )
    )
    await session.commit()
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="catora-demo-remediation-backlog.csv"'
        },
    )


@router.get("/workspaces/{workspace_id}/demo/report.pptx")
async def download_demo_report(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Response:
    await auth_service.membership(session, context.user.id, workspace_id)
    overview = await service.overview(session, workspace_id=workspace_id)
    payload = build_demo_pptx(overview)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="demo.report_downloaded",
            entity_type="workspace",
            entity_id=workspace_id,
            payload={"format": "pptx", "size_bytes": len(payload)},
        )
    )
    await session.commit()
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="catora-executive-assessment.pptx"'
        },
    )
