from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    IngestionJob,
    Organization,
    ReportJob,
    Workspace,
)
from catora_api.diagnostics.reporting import (
    build_backlog_csv,
    build_report_pptx,
    load_report,
)
from catora_api.diagnostics.service import (
    ASSESSMENT_TYPE,
    DiagnosticNotFoundError,
    DiagnosticService,
)
from catora_api.ingestion.factory import connector_for_source
from catora_api.schemas.diagnostics import (
    DiagnosticCreateRequest,
    DiagnosticRejectionList,
    DiagnosticView,
)
from catora_api.storage import ObjectStorage
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["prospect diagnostics"])
service = DiagnosticService()


def get_object_storage(settings: SettingsDependency) -> ObjectStorage:
    return ObjectStorage(settings)


StorageDependency = Annotated[ObjectStorage, Depends(get_object_storage)]


def _require_diagnostic_manager(role: str) -> None:
    if not can(Role(role), "diagnostics.manage"):
        raise AuthorizationError(
            "Prospect diagnostic management requires owner or admin access"
        )


async def _assessment_for_user(
    *,
    assessment_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    user_id: uuid.UUID,
    require_manage: bool = False,
) -> ReportJob:
    try:
        assessment = await service.get(session, assessment_id)
    except DiagnosticNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    membership = await auth_service.membership(
        session,
        user_id,
        assessment.workspace_id,
    )
    if require_manage:
        _require_diagnostic_manager(membership.role)
    return assessment


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@router.post(
    "/workspaces/{operator_workspace_id}/prospect-diagnostics",
    response_model=DiagnosticView,
    status_code=status.HTTP_201_CREATED,
)
async def create_prospect_diagnostic(
    operator_workspace_id: uuid.UUID,
    payload: DiagnosticCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DiagnosticView:
    membership = await auth_service.membership(
        session,
        context.user.id,
        operator_workspace_id,
    )
    _require_diagnostic_manager(membership.role)
    assessment = await service.create(
        session,
        actor_user_id=context.user.id,
        actor_role=membership.role,
        operator_workspace_id=operator_workspace_id,
        payload=payload,
    )
    return await service.view(session, assessment)


@router.put(
    "/prospect-diagnostics/{assessment_id}/catalog.csv",
    response_model=DiagnosticView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_prospect_catalog(
    assessment_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DiagnosticView:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
        require_manage=True,
    )
    if assessment.status not in {"awaiting_upload", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "This diagnostic already has an active or completed "
                "catalog assessment"
            ),
        )

    content_type = request.headers.get("content-type", "text/csv").split(";", 1)[0]
    if content_type not in {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
    }:
        raise HTTPException(
            status_code=415,
            detail="Upload must use a CSV content type",
        )
    content_buffer = bytearray()
    async for chunk in request.stream():
        if len(content_buffer) + len(chunk) > settings.max_catalog_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail="CSV upload exceeds configured size limit",
            )
        content_buffer.extend(chunk)
    if not content_buffer:
        raise HTTPException(status_code=400, detail="CSV upload cannot be empty")

    workspace_id = assessment.workspace_id
    object_key = (
        f"workspaces/{workspace_id}/diagnostics/{assessment.id}/"
        "shopify-products.csv"
    )
    stored = await storage.put_bytes(
        object_key,
        bytes(content_buffer),
        content_type="text/csv",
    )
    snapshot = dict(assessment.input_snapshot)
    company_name = snapshot.get("company_name")
    company_label = company_name if isinstance(company_name, str) else "Prospect"
    storefront_id = _snapshot_uuid(snapshot, "storefront_id")
    source = CatalogSource(
        workspace_id=workspace_id,
        storefront_id=storefront_id,
        name=f"{company_label} Shopify product export",
        source_type="csv",
        status="draft",
        config={
            "profile": "shopify",
            "object_key": object_key,
            "encoding": "utf-8-sig",
            "delimiter": None,
            "mapping": {
                "product_id": "Handle",
                "title": "Title",
                "variant_id": "Variant SKU",
                "sku": "Variant SKU",
                "description": "Body (HTML)",
                "price": "Variant Price",
                "availability": "Variant Inventory Qty",
                "category": "Type",
                "image_url": "Image Src",
            },
        },
    )
    session.add(source)
    await session.flush()
    connector = await connector_for_source(source, storage)
    validation = await connector.validate()
    if not validation.valid:
        source.status = "invalid"
        await service.set_status(
            session,
            assessment,
            "awaiting_upload",
            object_key=object_key,
            upload_size_bytes=stored.size_bytes,
            validation_errors=list(validation.errors),
            validation_warnings=list(validation.warnings),
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=context.user.id,
                event_type="diagnostic.upload_rejected",
                entity_type="report_job",
                entity_id=assessment.id,
                payload={
                    "size_bytes": stored.size_bytes,
                    "error_count": len(validation.errors),
                    "warning_count": len(validation.warnings),
                },
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail=(
                " ".join(validation.errors)
                or "The Shopify CSV could not be validated"
            ),
        )

    source.status = "ready"
    job = IngestionJob(
        workspace_id=workspace_id,
        catalog_source_id=source.id,
        status="queued",
        checkpoint={
            "validation_errors": [],
            "validation_warnings": list(validation.warnings),
        },
    )
    session.add(job)
    await session.flush()
    await service.set_status(
        session,
        assessment,
        "queued",
        object_key=object_key,
        upload_size_bytes=stored.size_bytes,
        catalog_source_id=str(source.id),
        ingestion_job_id=str(job.id),
        validation_errors=[],
        validation_warnings=list(validation.warnings),
        discovered_fields=list(validation.discovered_fields),
        failure_code=None,
        failure_detail=None,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="diagnostic.catalog_queued",
            entity_type="report_job",
            entity_id=assessment.id,
            payload={
                "catalog_source_id": str(source.id),
                "ingestion_job_id": str(job.id),
                "size_bytes": stored.size_bytes,
                "validation_warning_count": len(validation.warnings),
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task(
            "catora.diagnostic.run",
            args=[str(assessment.id)],
        )
    except Exception as exc:
        job.status = "failed"
        await service.set_status(
            session,
            assessment,
            "failed",
            failure_code=type(exc).__name__,
            failure_detail="The diagnostic worker could not be queued.",
        )
        raise HTTPException(
            status_code=503,
            detail="Unable to queue the diagnostic",
        ) from exc
    await session.refresh(assessment)
    return await service.view(session, assessment)


@router.get(
    "/prospect-diagnostics/{assessment_id}",
    response_model=DiagnosticView,
)
async def get_prospect_diagnostic(
    assessment_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> DiagnosticView:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
    )
    return await service.view(session, assessment)


@router.get(
    "/prospect-diagnostics/{assessment_id}/rejections",
    response_model=DiagnosticRejectionList,
)
async def get_prospect_diagnostic_rejections(
    assessment_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> DiagnosticRejectionList:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
    )
    return await service.rejection_list(session, assessment)


@router.get("/prospect-diagnostics/{assessment_id}/backlog.csv")
async def download_prospect_backlog(
    assessment_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Response:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
    )
    if assessment.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="The assessment backlog is not ready",
        )
    report = await load_report(session, assessment)
    payload = build_backlog_csv(report)
    session.add(
        AuditEvent(
            workspace_id=assessment.workspace_id,
            actor_user_id=context.user.id,
            event_type="diagnostic.backlog_downloaded",
            entity_type="report_job",
            entity_id=assessment.id,
            payload={"row_count": len(report.findings)},
        )
    )
    await session.commit()
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="catora-prospect-remediation-backlog.csv"'
            )
        },
    )


@router.get("/prospect-diagnostics/{assessment_id}/report.pptx")
async def download_prospect_report(
    assessment_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Response:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
    )
    if assessment.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="The assessment report is not ready",
        )
    report = await load_report(session, assessment)
    payload = build_report_pptx(report)
    session.add(
        AuditEvent(
            workspace_id=assessment.workspace_id,
            actor_user_id=context.user.id,
            event_type="diagnostic.report_downloaded",
            entity_type="report_job",
            entity_id=assessment.id,
            payload={"format": "pptx", "size_bytes": len(payload)},
        )
    )
    await session.commit()
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="catora-prospect-executive-assessment.pptx"'
            )
        },
    )


@router.delete(
    "/prospect-diagnostics/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_prospect_diagnostic(
    assessment_id: uuid.UUID,
    session: SessionDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> None:
    assessment = await _assessment_for_user(
        assessment_id=assessment_id,
        session=session,
        auth_service=auth_service,
        user_id=context.user.id,
        require_manage=True,
    )
    snapshot = dict(assessment.input_snapshot)
    object_key = snapshot.get("object_key")
    operator_workspace_id = _snapshot_uuid(
        snapshot,
        "operator_workspace_id",
    )
    await service.set_status(session, assessment, "deleting")
    if isinstance(object_key, str):
        await storage.delete(object_key)
    if operator_workspace_id is not None:
        session.add(
            AuditEvent(
                workspace_id=operator_workspace_id,
                actor_user_id=context.user.id,
                event_type="diagnostic.deleted",
                entity_type="workspace",
                entity_id=assessment.workspace_id,
                payload={"assessment_id": str(assessment.id)},
            )
        )
    organization_id = _snapshot_uuid(snapshot, "organization_id")
    if organization_id is None:
        raise HTTPException(status_code=409, detail="Diagnostic organization is unavailable")
    await session.execute(
        delete(Organization).where(Organization.id == organization_id)
    )
    await session.commit()


@router.post(
    "/workspaces/{operator_workspace_id}/prospect-diagnostics/purge-expired"
)
async def purge_expired_diagnostics(
    operator_workspace_id: uuid.UUID,
    session: SessionDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, int]:
    membership = await auth_service.membership(
        session,
        context.user.id,
        operator_workspace_id,
    )
    _require_diagnostic_manager(membership.role)
    assessments = list(
        (
            await session.scalars(
                select(ReportJob)
                .where(ReportJob.report_type == ASSESSMENT_TYPE)
                .order_by(ReportJob.created_at)
                .limit(200)
            )
        ).all()
    )
    now = datetime.now(UTC)
    purged = 0
    for assessment in assessments:
        snapshot = dict(assessment.input_snapshot)
        if (
            _snapshot_uuid(snapshot, "operator_workspace_id")
            != operator_workspace_id
        ):
            continue
        expires = snapshot.get("retention_expires_at")
        if not isinstance(expires, str):
            continue
        try:
            expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires_at > now:
            continue
        object_key = snapshot.get("object_key")
        if isinstance(object_key, str):
            await storage.delete(object_key)
        organization_id = _snapshot_uuid(snapshot, "organization_id")
        if organization_id is None:
            continue
        await session.execute(
            delete(Organization).where(Organization.id == organization_id)
        )
        purged += 1
    if purged:
        session.add(
            AuditEvent(
                workspace_id=operator_workspace_id,
                actor_user_id=context.user.id,
                event_type="diagnostic.retention_purge_completed",
                entity_type="workspace",
                entity_id=operator_workspace_id,
                payload={"purged_count": purged},
            )
        )
    await session.commit()
    return {"purged_count": purged}
