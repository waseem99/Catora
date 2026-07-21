from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError, ConflictError
from catora_api.db.models import AuditEvent, Membership
from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.ingestion.factory import connector_for_source
from catora_api.schemas.ingestion import (
    CatalogSourceView,
    CsvSourceCreateRequest,
    CsvUploadResponse,
    IngestionJobView,
    SourceRecordSample,
    SourceValidationResponse,
)
from catora_api.storage import ObjectStorage
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["catalog ingestion"])
ACTIVE_JOB_STATUSES = ("queued", "validating", "running")


def get_object_storage(settings: SettingsDependency) -> ObjectStorage:
    return ObjectStorage(settings)


StorageDependency = Annotated[ObjectStorage, Depends(get_object_storage)]


async def _membership(
    *,
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Membership:
    return await auth_service.membership(session, context.user.id, workspace_id)


def _require_source_write(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


def _source_view(source: CatalogSource) -> CatalogSourceView:
    return CatalogSourceView.model_validate(source)


def _job_view(job: IngestionJob) -> IngestionJobView:
    safe_checkpoint_keys = {
        "connector",
        "duplicate_count",
        "validation_errors",
        "validation_warnings",
        "error_type",
        "error_message",
    }
    safe_checkpoint = {
        key: value for key, value in job.checkpoint.items() if key in safe_checkpoint_keys
    }
    return IngestionJobView(
        id=job.id,
        workspace_id=job.workspace_id,
        catalog_source_id=job.catalog_source_id,
        status=job.status,  # type: ignore[arg-type]
        processed_count=job.processed_count,
        success_count=job.success_count,
        rejection_count=job.rejection_count,
        warning_count=job.warning_count,
        checkpoint=safe_checkpoint,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.put(
    "/workspaces/{workspace_id}/catalog-uploads/csv",
    response_model=CsvUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_csv(
    workspace_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CsvUploadResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    content_buffer = bytearray()
    async for chunk in request.stream():
        if len(content_buffer) + len(chunk) > settings.max_catalog_upload_bytes:
            raise HTTPException(
                status_code=413, detail="CSV upload exceeds configured size limit"
            )
        content_buffer.extend(chunk)
    if not content_buffer:
        raise HTTPException(status_code=400, detail="CSV upload cannot be empty")
    content = bytes(content_buffer)
    content_type = request.headers.get("content-type", "text/csv").split(";", 1)[0]
    if content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=415, detail="Upload must use a CSV content type")

    object_key = f"workspaces/{workspace_id}/catalog-uploads/{uuid.uuid4()}.csv"
    stored = await storage.put_bytes(object_key, content, content_type="text/csv")
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.csv_uploaded",
            entity_type="object",
            payload={"object_key": stored.key, "size_bytes": stored.size_bytes},
        )
    )
    await session.commit()
    return CsvUploadResponse(
        object_key=stored.key,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )


@router.post(
    "/workspaces/{workspace_id}/catalog-sources",
    response_model=CatalogSourceView,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_source(
    workspace_id: uuid.UUID,
    payload: CsvSourceCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CatalogSourceView:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    if not payload.object_key.startswith(f"workspaces/{workspace_id}/"):
        raise AuthorizationError("Uploaded object does not belong to this workspace")

    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type=payload.source_type,
        status="draft",
        config={
            "object_key": payload.object_key,
            "mapping": payload.mapping.model_dump(exclude_none=True),
            "encoding": payload.encoding,
            "delimiter": payload.delimiter,
        },
    )
    session.add(source)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={"source_type": source.source_type, "name": source.name},
        )
    )
    await session.commit()
    await session.refresh(source)
    return _source_view(source)


@router.get(
    "/workspaces/{workspace_id}/catalog-sources",
    response_model=list[CatalogSourceView],
)
async def list_catalog_sources(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[CatalogSourceView]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    sources = (
        await session.scalars(
            select(CatalogSource)
            .where(
                CatalogSource.workspace_id == workspace_id,
                CatalogSource.deleted_at.is_(None),
            )
            .order_by(CatalogSource.created_at.desc())
        )
    ).all()
    return [_source_view(source) for source in sources]


@router.post(
    "/workspaces/{workspace_id}/catalog-sources/{source_id}/validate",
    response_model=SourceValidationResponse,
)
async def validate_catalog_source(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> SourceValidationResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    source = await session.scalar(
        select(CatalogSource).where(
            CatalogSource.id == source_id,
            CatalogSource.workspace_id == workspace_id,
            CatalogSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Catalog source not found")
    connector = await connector_for_source(source, storage)
    validation = await connector.validate()
    source.status = "ready" if validation.valid else "invalid"
    await session.commit()
    return SourceValidationResponse(
        valid=validation.valid,
        errors=list(validation.errors),
        warnings=list(validation.warnings),
        discovered_fields=list(validation.discovered_fields),
    )


@router.post(
    "/workspaces/{workspace_id}/catalog-sources/{source_id}/jobs",
    response_model=IngestionJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_ingestion_job(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IngestionJobView:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    source = await session.scalar(
        select(CatalogSource).where(
            CatalogSource.id == source_id,
            CatalogSource.workspace_id == workspace_id,
            CatalogSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Catalog source not found")
    active_job = await session.scalar(
        select(IngestionJob.id).where(
            IngestionJob.catalog_source_id == source_id,
            IngestionJob.workspace_id == workspace_id,
            IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_job is not None:
        raise ConflictError("An ingestion job is already active for this source")

    job = IngestionJob(
        workspace_id=workspace_id,
        catalog_source_id=source_id,
        status="queued",
        checkpoint={},
    )
    session.add(job)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.ingestion_queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            payload={"catalog_source_id": str(source_id)},
        )
    )
    await session.commit()
    try:
        celery_app.send_task("catora.ingestion.run", args=[str(job.id)])
    except Exception as exc:
        job.status = "failed"
        job.checkpoint = {
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue ingestion job",
        }
        await session.commit()
        raise HTTPException(status_code=503, detail="Unable to enqueue ingestion job") from exc
    await session.refresh(job)
    return _job_view(job)


@router.get(
    "/workspaces/{workspace_id}/ingestion-jobs",
    response_model=list[IngestionJobView],
)
async def list_ingestion_jobs(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[IngestionJobView]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    jobs = (
        await session.scalars(
            select(IngestionJob)
            .where(IngestionJob.workspace_id == workspace_id)
            .order_by(IngestionJob.created_at.desc())
        )
    ).all()
    return [_job_view(job) for job in jobs]


@router.post(
    "/workspaces/{workspace_id}/ingestion-jobs/{job_id}/cancel",
    response_model=IngestionJobView,
)
async def cancel_ingestion_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IngestionJobView:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    if job.status not in ACTIVE_JOB_STATUSES:
        raise ConflictError("Only an active ingestion job can be cancelled")
    job.status = "cancelled"
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.ingestion_cancelled",
            entity_type="ingestion_job",
            entity_id=job.id,
        )
    )
    await session.commit()
    await session.refresh(job)
    return _job_view(job)


@router.get(
    "/workspaces/{workspace_id}/catalog-sources/{source_id}/records",
    response_model=list[SourceRecordSample],
)
async def sample_source_records(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    limit: int = 20,
) -> list[SourceRecordSample]:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    bounded_limit = max(1, min(limit, 100))
    records = (
        await session.scalars(
            select(SourceRecord)
            .where(
                SourceRecord.workspace_id == workspace_id,
                SourceRecord.catalog_source_id == source_id,
            )
            .order_by(SourceRecord.snapshot_at.desc())
            .limit(bounded_limit)
        )
    ).all()
    return [SourceRecordSample.model_validate(record) for record in records]
