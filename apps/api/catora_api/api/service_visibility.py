# ruff: noqa: E501
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
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
from catora_api.db.models import AuditEvent, ExportArtifact, Membership, ReportJob
from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.schemas.service_visibility import (
    SERVICE_VISIBILITY_PROTOCOL_VERSION,
    ServicePageSnapshot,
    ServiceVisibilityBridgeBatch,
    ServiceVisibilityReportResponse,
    ServiceVisibilityRunResponse,
    ServiceVisibilityScorecard,
    ServiceVisibilitySourceCreateRequest,
    ServiceVisibilitySourceProvisionResponse,
)
from catora_api.service_visibility.engine import build_scorecard
from catora_api.service_visibility.reports import (
    artifact_metadata,
    content_brief,
    executive_pptx,
    findings_csv,
)
from catora_api.service_visibility.security import issue_token, verify_signed_body
from catora_api.storage import ObjectStorage
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["service visibility"])


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


def _require_write(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Service visibility source management permission required")


def _config(source: CatalogSource) -> dict[str, Any]:
    value = source.config.get("service_visibility")
    return dict(value) if isinstance(value, dict) else {}


async def _workspace_source(
    session: SessionDependency,
    *,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    lock: bool = False,
) -> CatalogSource:
    query = select(CatalogSource).where(
        CatalogSource.id == source_id,
        CatalogSource.workspace_id == workspace_id,
        CatalogSource.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    source = await session.scalar(query)
    if source is None or not _config(source):
        raise HTTPException(status_code=404, detail="Service visibility source not found")
    return source


async def _public_source(
    session: SessionDependency,
    *,
    source_id: uuid.UUID,
) -> CatalogSource:
    source = await session.scalar(
        select(CatalogSource)
        .where(
            CatalogSource.id == source_id,
            CatalogSource.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if source is None or not _config(source):
        raise HTTPException(status_code=404, detail="Service visibility source not found")
    return source


async def _latest_job(session: SessionDependency, source: CatalogSource) -> IngestionJob:
    job = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.catalog_source_id == source.id,
            IngestionJob.status.in_(("completed", "partially_completed")),
        )
        .order_by(IngestionJob.completed_at.desc().nullslast(), IngestionJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="No completed service visibility snapshot")
    return job


async def _pages_for_job(
    session: SessionDependency,
    *,
    source: CatalogSource,
    job: IngestionJob,
) -> tuple[ServicePageSnapshot, ...]:
    records = (
        await session.scalars(
            select(SourceRecord)
            .where(
                SourceRecord.catalog_source_id == source.id,
                SourceRecord.record_type == "service_page",
                SourceRecord.last_seen_job_id == job.id,
            )
            .order_by(SourceRecord.external_id)
        )
    ).all()
    pages: list[ServicePageSnapshot] = []
    for record in records:
        try:
            pages.append(ServicePageSnapshot.model_validate(record.payload))
        except ValidationError:
            continue
    return tuple(pages)


async def _latest_scorecard(
    session: SessionDependency,
    source: CatalogSource,
) -> ServiceVisibilityScorecard:
    job = await _latest_job(session, source)
    return build_scorecard(source.id, job.id, await _pages_for_job(session, source=source, job=job))


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources",
    response_model=ServiceVisibilitySourceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    workspace_id: uuid.UUID,
    payload: ServiceVisibilitySourceCreateRequest,
    request: Request,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilitySourceProvisionResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_write(membership.role)
    start_url = str(payload.start_url)
    host = urlparse(start_url).hostname
    if not host:
        raise HTTPException(status_code=422, detail="Start URL must include a host")
    token: str | None = None
    token_hash: str | None = None
    fingerprint: str | None = None
    if payload.connection_mode == "wordpress_bridge":
        token, token_hash, fingerprint = issue_token()
    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type="urls",
        status="ready",
        config={
            "start_url": start_url,
            "product_urls": [start_url],
            "authorized_domain_confirmed": True,
            "max_products": payload.max_pages,
            "max_sitemaps": 10,
            "crawl_delay_seconds": 0.1,
            "normalization_aliases": {},
            "service_visibility": {
                "connection_mode": payload.connection_mode,
                "exact_host": host,
                "max_pages": payload.max_pages,
                "token_hash": token_hash,
                "token_fingerprint": fingerprint,
                "drafts_enabled": False,
                "monitoring_enabled": False,
            },
        },
    )
    session.add(source)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="service_visibility.source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={
                "connection_mode": payload.connection_mode,
                "host": host,
                "max_pages": payload.max_pages,
                "token_fingerprint": fingerprint,
            },
        )
    )
    await session.commit()
    endpoint = None
    if token is not None:
        endpoint = f"{str(request.base_url).rstrip('/')}/api/v1/service-visibility/sources/{source.id}/snapshots"
    return ServiceVisibilitySourceProvisionResponse(
        sourceId=source.id,
        connectionMode=payload.connection_mode,
        endpoint=endpoint,
        token=token,
        tokenFingerprint=fingerprint,
        protocolVersion=SERVICE_VISIBILITY_PROTOCOL_VERSION,
    )


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/runs",
    response_model=ServiceVisibilityRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_zero_install_run(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilityRunResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_write(membership.role)
    source = await _workspace_source(
        session,
        workspace_id=workspace_id,
        source_id=source_id,
        lock=True,
    )
    if _config(source).get("connection_mode") != "zero_install":
        raise ConflictError("This source accepts signed WordPress snapshots instead")
    active = await session.scalar(
        select(IngestionJob.id).where(
            IngestionJob.catalog_source_id == source.id,
            IngestionJob.status.in_(("queued", "validating", "running")),
        )
    )
    if active is not None:
        raise ConflictError("A service visibility run is already active")
    job = IngestionJob(workspace_id=workspace_id, catalog_source_id=source.id, status="queued")
    session.add(job)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="service_visibility.run_queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            payload={"catalog_source_id": str(source.id)},
        )
    )
    await session.commit()
    celery_app.send_task("catora.service_visibility.run", args=[str(job.id)])
    return ServiceVisibilityRunResponse(sourceId=source.id, jobId=job.id, status="queued")


@router.post(
    "/service-visibility/sources/{source_id}/snapshots",
    response_model=ServiceVisibilityRunResponse,
)
async def receive_wordpress_snapshot(
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    token: Annotated[str | None, Header(alias="X-Catora-Token")] = None,
    timestamp: Annotated[str | None, Header(alias="X-Catora-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Catora-Signature")] = None,
) -> ServiceVisibilityRunResponse:
    source = await _public_source(session, source_id=source_id)
    config = _config(source)
    if config.get("connection_mode") != "wordpress_bridge":
        raise HTTPException(status_code=404, detail="WordPress bridge source not found")
    if not token or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Signed bridge headers are required")
    body = await request.body()
    if len(body) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Snapshot batch is too large")
    try:
        verify_signed_body(
            token=token,
            expected_token_hash=str(config.get("token_hash") or ""),
            timestamp=timestamp,
            signature=signature,
            body=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        batch = ServiceVisibilityBridgeBatch.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_input=False),
        ) from exc
    if config.get("last_snapshot_id") == str(batch.snapshot_id):
        last_job_id = config.get("last_job_id")
        if isinstance(last_job_id, str):
            completed_job = await session.get(IngestionJob, uuid.UUID(last_job_id))
            if completed_job is not None:
                return ServiceVisibilityRunResponse(
                    sourceId=source.id,
                    jobId=completed_job.id,
                    status=completed_job.status,
                )
    exact_host = str(config.get("exact_host") or "")
    for page in batch.pages:
        if urlparse(str(page.canonical_url)).hostname != exact_host:
            raise HTTPException(
                status_code=422,
                detail="WordPress snapshot page left the authorized host",
            )
        if any(urlparse(str(link)).hostname != exact_host for link in page.internal_links):
            raise HTTPException(
                status_code=422,
                detail="WordPress snapshot contains off-host internal links",
            )
    snapshot = config.get("active_snapshot")
    active = dict(snapshot) if isinstance(snapshot, dict) else {}
    if not active:
        if batch.sequence != 0:
            raise ConflictError("The first WordPress snapshot batch must use sequence 0")
        job = IngestionJob(
            workspace_id=source.workspace_id,
            catalog_source_id=source.id,
            status="running",
            checkpoint={"snapshot_id": str(batch.snapshot_id), "received_sequences": []},
        )
        session.add(job)
        await session.flush()
        active = {"snapshot_id": str(batch.snapshot_id), "job_id": str(job.id)}
    elif active.get("snapshot_id") != str(batch.snapshot_id):
        raise ConflictError("A different WordPress snapshot is already active")
    job = await session.get(IngestionJob, uuid.UUID(str(active["job_id"])))
    if job is None:
        raise HTTPException(status_code=409, detail="WordPress snapshot job is unavailable")
    checkpoint = dict(job.checkpoint)
    sequences = [int(value) for value in checkpoint.get("received_sequences", [])]
    checksums_value = checkpoint.get("batch_checksums")
    checksums = dict(checksums_value) if isinstance(checksums_value, dict) else {}
    body_checksum = hashlib.sha256(body).hexdigest()
    if batch.sequence in sequences:
        if checksums.get(str(batch.sequence)) != body_checksum:
            raise ConflictError("WordPress snapshot sequence was already used with different content")
        return ServiceVisibilityRunResponse(sourceId=source.id, jobId=job.id, status=job.status)
    if batch.sequence != len(sequences):
        raise ConflictError("WordPress snapshot batches must be uploaded in sequence")
    for page in batch.pages:
        existing = await session.scalar(
            select(SourceRecord).where(
                SourceRecord.catalog_source_id == source.id,
                SourceRecord.external_id == str(page.canonical_url),
                SourceRecord.content_hash == page.content_hash,
            )
        )
        if existing is not None:
            existing.last_seen_job_id = job.id
            continue
        session.add(
            SourceRecord(
                workspace_id=source.workspace_id,
                catalog_source_id=source.id,
                ingestion_job_id=job.id,
                last_seen_job_id=job.id,
                external_id=str(page.canonical_url),
                record_type="service_page",
                payload=page.model_dump(mode="json", by_alias=True),
                content_hash=page.content_hash,
                source_updated_at=page.updated_at,
            )
        )
    sequences.append(batch.sequence)
    checksums[str(batch.sequence)] = body_checksum
    job.processed_count += len(batch.pages)
    job.success_count += len(batch.pages)
    checkpoint["received_sequences"] = sequences
    checkpoint["batch_checksums"] = checksums
    job.checkpoint = checkpoint
    if batch.complete:
        pages = await _pages_for_job(session, source=source, job=job)
        scorecard = build_scorecard(source.id, job.id, pages)
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.checkpoint = {
            **checkpoint,
            "score_basis_points": scorecard.score_basis_points,
            "finding_count": len(scorecard.findings),
            "question_count": len(scorecard.questions),
        }
        config.pop("active_snapshot", None)
        config["last_snapshot_id"] = str(batch.snapshot_id)
        config["last_job_id"] = str(job.id)
        source.status = "ready"
        session.add(
            AuditEvent(
                workspace_id=source.workspace_id,
                actor_user_id=None,
                event_type="service_visibility.wordpress_snapshot_completed",
                entity_type="ingestion_job",
                entity_id=job.id,
                payload={
                    "snapshot_id": str(batch.snapshot_id),
                    "page_count": len(pages),
                    "score_basis_points": scorecard.score_basis_points,
                    "token_fingerprint": config.get("token_fingerprint"),
                },
            )
        )
    else:
        config["active_snapshot"] = active
        source.status = "syncing"
    source.config = {**dict(source.config), "service_visibility": config}
    await session.commit()
    return ServiceVisibilityRunResponse(sourceId=source.id, jobId=job.id, status=job.status)


@router.get(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/latest",
    response_model=ServiceVisibilityScorecard,
)
async def latest_scorecard(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ServiceVisibilityScorecard:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    source = await _workspace_source(session, workspace_id=workspace_id, source_id=source_id)
    return await _latest_scorecard(session, source)


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/reports",
    response_model=ServiceVisibilityReportResponse,
)
async def create_reports(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilityReportResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_write(membership.role)
    source = await _workspace_source(session, workspace_id=workspace_id, source_id=source_id)
    scorecard = await _latest_scorecard(session, source)
    report = ReportJob(
        workspace_id=workspace_id,
        report_type="service_visibility_audit",
        status="completed",
        input_snapshot={
            "source_id": str(source.id),
            "ingestion_job_id": str(scorecard.job_id),
            "score_basis_points": scorecard.score_basis_points,
        },
        template_version="2026-07-service-visibility-v1",
    )
    session.add(report)
    await session.flush()
    contents = {
        "csv": (findings_csv(scorecard), "text/csv"),
        "pptx": (
            executive_pptx(scorecard),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        "content_brief": (content_brief(scorecard), "text/markdown"),
    }
    result: list[dict[str, object]] = []
    for artifact_type, (content, content_type) in contents.items():
        key = f"workspaces/{workspace_id}/service-visibility/{report.id}/{artifact_type}"
        stored = await storage.put_bytes(key, content, content_type=content_type)
        checksum, size = artifact_metadata(content)
        artifact = ExportArtifact(
            workspace_id=workspace_id,
            report_job_id=report.id,
            artifact_type=artifact_type,
            object_key=stored.key,
            checksum=checksum,
            size_bytes=size,
        )
        session.add(artifact)
        await session.flush()
        result.append(
            {
                "artifactId": str(artifact.id),
                "artifactType": artifact_type,
                "objectKey": stored.key,
                "checksum": checksum,
                "sizeBytes": size,
            }
        )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="service_visibility.reports_created",
            entity_type="report_job",
            entity_id=report.id,
            payload={"artifact_types": sorted(contents), "source_id": str(source.id)},
        )
    )
    await session.commit()
    return ServiceVisibilityReportResponse(reportJobId=report.id, artifacts=result)


@router.get(
    "/workspaces/{workspace_id}/service-visibility/artifacts/{artifact_id}",
)
async def download_artifact(
    workspace_id: uuid.UUID,
    artifact_id: uuid.UUID,
    session: SessionDependency,
    storage: StorageDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Response:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    artifact = await session.scalar(
        select(ExportArtifact).where(
            ExportArtifact.id == artifact_id,
            ExportArtifact.workspace_id == workspace_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Service visibility artifact not found")
    media = {
        "csv": "text/csv",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "content_brief": "text/markdown",
    }.get(artifact.artifact_type, "application/octet-stream")
    return Response(content=await storage.get_bytes(artifact.object_key), media_type=media)


@router.get(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/comparison",
)
async def compare_latest_runs(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    source = await _workspace_source(
        session,
        workspace_id=workspace_id,
        source_id=source_id,
    )
    jobs = list(
        (
            await session.scalars(
                select(IngestionJob)
                .where(
                    IngestionJob.catalog_source_id == source.id,
                    IngestionJob.status.in_(("completed", "partially_completed")),
                )
                .order_by(
                    IngestionJob.completed_at.desc().nullslast(),
                    IngestionJob.created_at.desc(),
                )
                .limit(2)
            )
        ).all()
    )
    if len(jobs) < 2:
        raise HTTPException(status_code=404, detail="Two completed snapshots are required")
    current = build_scorecard(
        source.id,
        jobs[0].id,
        await _pages_for_job(session, source=source, job=jobs[0]),
    )
    previous = build_scorecard(
        source.id,
        jobs[1].id,
        await _pages_for_job(session, source=source, job=jobs[1]),
    )
    current_keys = {(item.rule_id, str(item.url or "")) for item in current.findings}
    previous_keys = {(item.rule_id, str(item.url or "")) for item in previous.findings}
    return {
        "previousJobId": str(previous.job_id),
        "currentJobId": str(current.job_id),
        "scoreDeltaBasisPoints": current.score_basis_points - previous.score_basis_points,
        "newFindingCount": len(current_keys - previous_keys),
        "resolvedFindingCount": len(previous_keys - current_keys),
        "unchangedFindingCount": len(current_keys & previous_keys),
    }


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/revoke",
)
async def revoke_bridge(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, str]:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_write(membership.role)
    source = await _workspace_source(
        session,
        workspace_id=workspace_id,
        source_id=source_id,
        lock=True,
    )
    config = _config(source)
    active = config.get("active_snapshot")
    if isinstance(active, dict) and isinstance(active.get("job_id"), str):
        active_job = await session.get(IngestionJob, uuid.UUID(active["job_id"]))
        if active_job is not None and active_job.status in {"queued", "validating", "running"}:
            active_job.status = "cancelled"
            active_job.completed_at = datetime.now(UTC)
    config["token_hash"] = None
    config["token_fingerprint"] = None
    config.pop("active_snapshot", None)
    source.config = {**dict(source.config), "service_visibility": config}
    source.status = "disconnected"
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="service_visibility.bridge_revoked",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={},
        )
    )
    await session.commit()
    return {"status": "disconnected"}


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/drafts",
)
async def drafts_disabled(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, str]:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_write(membership.role)
    source = await _workspace_source(session, workspace_id=workspace_id, source_id=source_id)
    if not cast(bool, _config(source).get("drafts_enabled", False)):
        raise HTTPException(
            status_code=409,
            detail="WordPress draft creation is disabled until a pilot records a commercial proceed decision",
        )
    raise HTTPException(status_code=501, detail="Draft creation is not part of the read-only release")
