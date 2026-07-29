# ruff: noqa: E501

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    ExportArtifact,
    IngestionJob,
    Membership,
    ReportJob,
)
from catora_api.schemas.service_visibility import (
    DraftProposalCreateRequest,
    DraftProposalView,
    DraftResultRequest,
    ServiceVisibilityRunView,
    ServiceVisibilitySourceCreateRequest,
    ServiceVisibilitySourceProvisionResponse,
    ServiceVisibilitySourceView,
    WordPressSnapshotBatch,
    WordPressSnapshotCompleteRequest,
    WordPressSnapshotManifest,
    WordPressSnapshotStatus,
)
from catora_api.service_visibility.security import ServiceVisibilityAuthenticator
from catora_api.service_visibility.tasks import (
    REPORT_TYPE,
    TEMPLATE_VERSION,
    run_service_visibility,
)
from catora_api.storage import ObjectStorage

router = APIRouter(prefix="/api/v1", tags=["service visibility"])
_ACTIVE_STATUSES = {"queued", "running"}


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _list_value(value: object) -> list[object]:
    return [item for item in value] if isinstance(value, list) else []


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
        raise AuthorizationError("Service visibility source management permission required")


def _require_analysis(role: str) -> None:
    if not can(Role(role), "analysis.run"):
        raise AuthorizationError("Service visibility analysis permission required")


def _require_review(role: str) -> None:
    if not can(Role(role), "recommendations.review"):
        raise AuthorizationError("Service visibility draft approval permission required")


def _source_view(source: CatalogSource) -> ServiceVisibilitySourceView:
    config = dict(source.config)
    credential = config.get("service_visibility_credential")
    fingerprint = credential.get("fingerprint") if isinstance(credential, dict) else None
    return ServiceVisibilitySourceView(
        id=source.id,
        workspace_id=cast(uuid.UUID, source.workspace_id),
        name=source.name,
        site_url=str(config.get("site_url") or ""),
        connection_mode=cast(Any, config.get("connection_mode") or "zero_install"),
        status=source.status,
        monitoring_enabled=config.get("monitoring_enabled") is True,
        token_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _run_view(report: ReportJob) -> ServiceVisibilityRunView:
    snapshot = dict(report.input_snapshot)
    source_id = uuid.UUID(str(snapshot["source_id"]))
    ingestion_job_id = uuid.UUID(str(snapshot["ingestion_job_id"]))
    artifacts = snapshot.get("artifacts")
    return ServiceVisibilityRunView(
        id=report.id,
        workspace_id=cast(uuid.UUID, report.workspace_id),
        source_id=source_id,
        ingestion_job_id=ingestion_job_id,
        status=report.status,
        scorecard={
            key: value
            for key, value in _dict_value(snapshot.get("scorecard")).items()
            if isinstance(value, int) and not isinstance(value, bool)
        },
        page_count=_int_value(snapshot.get("page_count")),
        finding_count=_int_value(snapshot.get("finding_count")),
        question_count=_int_value(snapshot.get("question_count")),
        continuity=_dict_value(snapshot.get("continuity")),
        artifacts=sorted(artifacts.keys()) if isinstance(artifacts, dict) else [],
        error=str(snapshot.get("error")) if snapshot.get("error") else None,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def _source_for_workspace(
    *,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    lock: bool = False,
) -> CatalogSource:
    query = select(CatalogSource).where(
        CatalogSource.id == source_id,
        CatalogSource.workspace_id == workspace_id,
        CatalogSource.source_type == "wordpress",
        CatalogSource.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    source = await session.scalar(query)
    if source is None:
        raise HTTPException(status_code=404, detail="Service visibility source not found")
    return source


async def _bridge_source(
    source_id: uuid.UUID,
    session: SessionDependency,
) -> CatalogSource:
    source = await session.scalar(
        select(CatalogSource)
        .where(
            CatalogSource.id == source_id,
            CatalogSource.source_type == "wordpress",
            CatalogSource.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if source is None or source.config.get("connection_mode") != "wordpress_bridge":
        raise HTTPException(status_code=404, detail="WordPress bridge source not found")
    return source


async def _authenticated_body(
    request: Request,
    *,
    source: CatalogSource,
    settings: SettingsDependency,
) -> bytes:
    if not settings.service_visibility_enabled:
        raise HTTPException(status_code=503, detail="Service visibility is disabled")
    body = await request.body()
    if len(body) > settings.service_visibility_max_batch_bytes:
        raise HTTPException(status_code=413, detail="Service visibility request is too large")
    await ServiceVisibilityAuthenticator(settings).authenticate(
        request,
        source=source,
        body=body,
    )
    return body


def _parse_json(model: type[Any], body: bytes) -> Any:
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False)) from exc


async def _queue_run(
    *,
    source: CatalogSource,
    session: SessionDependency,
    actor_user_id: uuid.UUID | None,
    trigger: str,
) -> ReportJob:
    config = dict(source.config)
    active = config.get("active_report_id")
    if isinstance(active, str):
        active_report = await session.get(ReportJob, uuid.UUID(active))
        if active_report is not None and active_report.status in _ACTIVE_STATUSES:
            raise ConflictError("A service visibility run is already active")
    mode = config.get("connection_mode")
    if mode == "wordpress_bridge":
        snapshot = config.get("service_visibility_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("status") != "complete":
            raise ConflictError("A complete WordPress snapshot is required before analysis")
    job = IngestionJob(
        workspace_id=source.workspace_id,
        catalog_source_id=source.id,
        status="queued",
        checkpoint={},
    )
    session.add(job)
    await session.flush()
    report = ReportJob(
        workspace_id=source.workspace_id,
        report_type=REPORT_TYPE,
        status="queued",
        template_version=TEMPLATE_VERSION,
        input_snapshot={
            "source_id": str(source.id),
            "ingestion_job_id": str(job.id),
            "trigger": trigger,
            "requested_by_user_id": str(actor_user_id) if actor_user_id else None,
        },
    )
    session.add(report)
    await session.flush()
    source.config = {**config, "active_report_id": str(report.id)}
    session.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=actor_user_id,
            event_type="service_visibility.run_queued",
            entity_type="report_job",
            entity_id=report.id,
            payload={"source_id": str(source.id), "trigger": trigger},
        )
    )
    await session.commit()
    await session.refresh(report)
    run_service_visibility.delay(str(report.id))
    return report


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources",
    response_model=ServiceVisibilitySourceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_visibility_source(
    workspace_id: uuid.UUID,
    payload: ServiceVisibilitySourceCreateRequest,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilitySourceProvisionResponse:
    if not settings.service_visibility_enabled:
        raise HTTPException(status_code=503, detail="Service visibility is disabled")
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    site_url = payload.site_url.rstrip("/")
    config: dict[str, object] = {
        "site_url": site_url,
        "connection_mode": payload.connection_mode,
        "authorized_domain_confirmed": True,
        "max_products": payload.max_pages,
        "max_sitemaps": payload.max_sitemaps,
        "crawl_delay_seconds": payload.crawl_delay_seconds,
        "monitoring_enabled": payload.monitoring_enabled,
        "draft_queue": [],
    }
    if payload.connection_mode == "zero_install":
        config["start_url"] = f"{site_url}/wp-sitemap.xml"
    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type="wordpress",
        status="draft",
        config=config,
    )
    session.add(source)
    await session.flush()
    token: str | None = None
    if payload.connection_mode == "wordpress_bridge":
        credential = ServiceVisibilityAuthenticator(settings).rotate(source)
        token = credential.token
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="service_visibility.source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={
                "site_host": urlparse(site_url).hostname,
                "connection_mode": payload.connection_mode,
                "monitoring_enabled": payload.monitoring_enabled,
            },
        )
    )
    await session.commit()
    await session.refresh(source)
    view = _source_view(source)
    return ServiceVisibilitySourceProvisionResponse(
        **view.model_dump(),
        endpoint=str(request.base_url).rstrip("/"),
        token=token,
    )


@router.get(
    "/workspaces/{workspace_id}/service-visibility/sources",
    response_model=list[ServiceVisibilitySourceView],
)
async def list_service_visibility_sources(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[ServiceVisibilitySourceView]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    sources = list(
        (
            await session.scalars(
                select(CatalogSource)
                .where(
                    CatalogSource.workspace_id == workspace_id,
                    CatalogSource.source_type == "wordpress",
                    CatalogSource.deleted_at.is_(None),
                )
                .order_by(CatalogSource.created_at.desc())
            )
        ).all()
    )
    return [_source_view(source) for source in sources]


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/rotate",
    response_model=ServiceVisibilitySourceProvisionResponse,
)
async def rotate_service_visibility_source(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilitySourceProvisionResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    source = await _source_for_workspace(
        workspace_id=workspace_id,
        source_id=source_id,
        session=session,
        lock=True,
    )
    if source.config.get("connection_mode") != "wordpress_bridge":
        raise ConflictError("Zero-install sources do not use bridge credentials")
    credential = ServiceVisibilityAuthenticator(settings).rotate(source)
    await session.commit()
    await session.refresh(source)
    return ServiceVisibilitySourceProvisionResponse(
        **_source_view(source).model_dump(),
        endpoint=str(request.base_url).rstrip("/"),
        token=credential.token,
    )


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/runs",
    response_model=ServiceVisibilityRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_service_visibility_run(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ServiceVisibilityRunView:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_analysis(membership.role)
    source = await _source_for_workspace(
        workspace_id=workspace_id,
        source_id=source_id,
        session=session,
        lock=True,
    )
    report = await _queue_run(
        source=source,
        session=session,
        actor_user_id=context.user.id,
        trigger="manual",
    )
    return _run_view(report)


@router.get(
    "/workspaces/{workspace_id}/service-visibility/runs",
    response_model=list[ServiceVisibilityRunView],
)
async def list_service_visibility_runs(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[ServiceVisibilityRunView]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    reports = list(
        (
            await session.scalars(
                select(ReportJob)
                .where(
                    ReportJob.workspace_id == workspace_id,
                    ReportJob.report_type == REPORT_TYPE,
                )
                .order_by(ReportJob.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [_run_view(report) for report in reports]


@router.get(
    "/workspaces/{workspace_id}/service-visibility/runs/{report_id}",
    response_model=ServiceVisibilityRunView,
)
async def get_service_visibility_run(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ServiceVisibilityRunView:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    report = await session.scalar(
        select(ReportJob).where(
            ReportJob.id == report_id,
            ReportJob.workspace_id == workspace_id,
            ReportJob.report_type == REPORT_TYPE,
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Service visibility run not found")
    return _run_view(report)


@router.get(
    "/workspaces/{workspace_id}/service-visibility/runs/{report_id}/artifacts/{artifact_type}",
)
async def download_service_visibility_artifact(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    artifact_type: str,
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
            ExportArtifact.workspace_id == workspace_id,
            ExportArtifact.report_job_id == report_id,
            ExportArtifact.artifact_type == artifact_type,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Service visibility artifact not found")
    content = await storage.get_bytes(artifact.object_key)
    content_types = {
        "service_visibility_json": "application/json",
        "service_visibility_findings_csv": "text/csv",
        "service_visibility_questions_csv": "text/csv",
        "service_visibility_content_brief": "text/markdown",
        "service_visibility_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    suffixes = {
        "service_visibility_json": "json",
        "service_visibility_findings_csv": "csv",
        "service_visibility_questions_csv": "csv",
        "service_visibility_content_brief": "md",
        "service_visibility_pptx": "pptx",
    }
    return Response(
        content=content,
        media_type=content_types.get(artifact_type, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="catora-service-visibility-{report_id}.{suffixes.get(artifact_type, "bin")}"'
        },
    )


def _drafts(source: CatalogSource) -> list[dict[str, object]]:
    value = source.config.get("draft_queue")
    return (
        [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )


def _draft_view(source: CatalogSource, draft: dict[str, object]) -> DraftProposalView:
    remote_draft_id = draft.get("remote_draft_id")
    return DraftProposalView(
        id=uuid.UUID(str(draft["id"])),
        source_id=source.id,
        report_id=uuid.UUID(str(draft["report_id"])),
        status=str(draft.get("status") or "pending"),
        page_url=str(draft.get("page_url") or ""),
        wordpress_post_id=_int_value(draft.get("wordpress_post_id")),
        base_revision=str(draft.get("base_revision") or ""),
        proposal=_dict_value(draft.get("proposal")),
        approved_at=datetime.fromisoformat(str(draft["approved_at"]))
        if draft.get("approved_at")
        else None,
        remote_draft_id=(
            remote_draft_id
            if isinstance(remote_draft_id, int) and not isinstance(remote_draft_id, bool)
            else None
        ),
        error=str(draft["error"]) if draft.get("error") else None,
    )


@router.post(
    "/workspaces/{workspace_id}/service-visibility/runs/{report_id}/drafts",
    response_model=DraftProposalView,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_visibility_draft(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    payload: DraftProposalCreateRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DraftProposalView:
    if not settings.service_visibility_drafts_enabled:
        raise HTTPException(status_code=503, detail="Service visibility drafts are disabled")
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_review(membership.role)
    report = await session.scalar(
        select(ReportJob).where(
            ReportJob.id == report_id,
            ReportJob.workspace_id == workspace_id,
            ReportJob.report_type == REPORT_TYPE,
            ReportJob.status == "completed",
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Completed service visibility run not found")
    source_id = uuid.UUID(str(report.input_snapshot["source_id"]))
    source = await _source_for_workspace(
        workspace_id=workspace_id,
        source_id=source_id,
        session=session,
        lock=True,
    )
    if source.config.get("connection_mode") != "wordpress_bridge":
        raise ConflictError("Draft delivery requires a WordPress bridge source")
    drafts = _drafts(source)
    draft = {
        "id": str(uuid.uuid4()),
        "report_id": str(report.id),
        "status": "pending",
        "page_url": payload.page_url,
        "wordpress_post_id": payload.wordpress_post_id,
        "base_revision": payload.base_revision,
        "proposal": payload.model_dump(
            exclude={"page_url", "wordpress_post_id", "base_revision"},
            exclude_none=True,
            mode="json",
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "created_by_user_id": str(context.user.id),
    }
    drafts.append(draft)
    source.config = {**dict(source.config), "draft_queue": drafts[-500:]}
    await session.commit()
    return _draft_view(source, draft)


@router.post(
    "/workspaces/{workspace_id}/service-visibility/sources/{source_id}/drafts/{draft_id}/approve",
    response_model=DraftProposalView,
)
async def approve_service_visibility_draft(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    draft_id: uuid.UUID,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> DraftProposalView:
    if not settings.service_visibility_drafts_enabled:
        raise HTTPException(status_code=503, detail="Service visibility drafts are disabled")
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_review(membership.role)
    source = await _source_for_workspace(
        workspace_id=workspace_id,
        source_id=source_id,
        session=session,
        lock=True,
    )
    drafts = _drafts(source)
    selected: dict[str, object] | None = None
    for draft in drafts:
        if draft.get("id") == str(draft_id):
            if draft.get("status") != "pending":
                raise ConflictError("Only pending proposals can be approved")
            draft["status"] = "approved"
            draft["approved_at"] = datetime.now(UTC).isoformat()
            draft["approved_by_user_id"] = str(context.user.id)
            selected = draft
            break
    if selected is None:
        raise HTTPException(status_code=404, detail="Draft proposal not found")
    source.config = {**dict(source.config), "draft_queue": drafts}
    await session.commit()
    return _draft_view(source, selected)


@router.post(
    "/service-visibility/sources/{source_id}/snapshots",
    response_model=WordPressSnapshotStatus,
)
async def begin_wordpress_snapshot(
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> WordPressSnapshotStatus:
    source = await _bridge_source(source_id, session)
    body = await _authenticated_body(request, source=source, settings=settings)
    manifest = cast(WordPressSnapshotManifest, _parse_json(WordPressSnapshotManifest, body))
    if manifest.site_url.rstrip("/") != str(source.config.get("site_url") or "").rstrip("/"):
        raise ConflictError("WordPress snapshot site does not match the source")
    current = source.config.get("service_visibility_snapshot")
    if isinstance(current, dict) and current.get("snapshot_id") == str(manifest.snapshot_id):
        return _snapshot_status(source, current)
    if isinstance(current, dict) and current.get("status") == "receiving":
        raise ConflictError("A WordPress snapshot is already active")
    snapshot = {
        "snapshot_id": str(manifest.snapshot_id),
        "status": "receiving",
        "declared_page_count": manifest.page_count,
        "started_at": manifest.started_at.isoformat(),
        "plugin_version": manifest.plugin_version,
        "batches": [],
        "accepted_page_count": 0,
        "ingestion_job_id": None,
        "report_id": None,
    }
    source.config = {**dict(source.config), "service_visibility_snapshot": snapshot}
    await session.commit()
    return _snapshot_status(source, snapshot)


@router.put(
    "/service-visibility/sources/{source_id}/snapshots/{snapshot_id}/batches/{sequence}",
    response_model=WordPressSnapshotStatus,
)
async def upload_wordpress_snapshot_batch(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    sequence: int,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    storage: StorageDependency,
) -> WordPressSnapshotStatus:
    source = await _bridge_source(source_id, session)
    body = await _authenticated_body(request, source=source, settings=settings)
    batch = cast(WordPressSnapshotBatch, _parse_json(WordPressSnapshotBatch, body))
    if batch.snapshot_id != snapshot_id or batch.sequence != sequence:
        raise ConflictError("WordPress batch path does not match its payload")
    snapshot_value = source.config.get("service_visibility_snapshot")
    snapshot = dict(snapshot_value) if isinstance(snapshot_value, dict) else {}
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="WordPress snapshot not found")
    if snapshot.get("status") != "receiving":
        raise ConflictError("WordPress snapshot is not accepting batches")
    batches_value = snapshot.get("batches")
    batches = (
        [dict(item) for item in batches_value if isinstance(item, dict)]
        if isinstance(batches_value, list)
        else []
    )
    checksum = hashlib.sha256(body).hexdigest()
    if sequence < len(batches):
        if batches[sequence].get("checksum") != checksum:
            raise ConflictError("WordPress batch sequence was already used")
        return _snapshot_status(source, snapshot)
    if sequence != len(batches):
        raise ConflictError("WordPress batches must be uploaded in sequence")
    key = f"workspaces/{source.workspace_id}/service-visibility/{source.id}/{snapshot_id}/{sequence:08d}.json"
    stored = await storage.put_bytes(key, body, content_type="application/json")
    batches.append(
        {
            "sequence": sequence,
            "object_key": stored.key,
            "checksum": checksum,
            "size_bytes": stored.size_bytes,
            "page_count": len(batch.records),
        }
    )
    snapshot["batches"] = batches
    snapshot["accepted_page_count"] = int(snapshot.get("accepted_page_count") or 0) + len(
        batch.records
    )
    source.config = {**dict(source.config), "service_visibility_snapshot": snapshot}
    await session.commit()
    return _snapshot_status(source, snapshot)


@router.post(
    "/service-visibility/sources/{source_id}/snapshots/{snapshot_id}/complete",
    response_model=WordPressSnapshotStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_wordpress_snapshot(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> WordPressSnapshotStatus:
    source = await _bridge_source(source_id, session)
    body = await _authenticated_body(request, source=source, settings=settings)
    payload = cast(
        WordPressSnapshotCompleteRequest,
        _parse_json(WordPressSnapshotCompleteRequest, body),
    )
    if payload.snapshot_id != snapshot_id:
        raise ConflictError("WordPress completion path does not match its payload")
    snapshot_value = source.config.get("service_visibility_snapshot")
    snapshot = dict(snapshot_value) if isinstance(snapshot_value, dict) else {}
    batches_value = snapshot.get("batches")
    batches = (
        [item for item in batches_value if isinstance(item, dict)]
        if isinstance(batches_value, list)
        else []
    )
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="WordPress snapshot not found")
    if snapshot.get("status") == "complete" and snapshot.get("report_id"):
        return _snapshot_status(source, snapshot)
    if len(batches) != payload.batch_count:
        raise ConflictError("WordPress batch count does not match")
    accepted = int(snapshot.get("accepted_page_count") or 0)
    if accepted != payload.page_count or accepted != int(snapshot.get("declared_page_count") or 0):
        raise ConflictError("WordPress page count does not match")
    snapshot["status"] = "complete"
    snapshot["completed_at"] = datetime.now(UTC).isoformat()
    source.config = {**dict(source.config), "service_visibility_snapshot": snapshot}
    report = await _queue_run(
        source=source,
        session=session,
        actor_user_id=None,
        trigger="wordpress_snapshot",
    )
    refreshed = _dict_value(source.config.get("service_visibility_snapshot"))
    refreshed["ingestion_job_id"] = str(report.input_snapshot["ingestion_job_id"])
    refreshed["report_id"] = str(report.id)
    source.config = {**dict(source.config), "service_visibility_snapshot": refreshed}
    await session.commit()
    return _snapshot_status(source, refreshed)


def _snapshot_status(source: CatalogSource, snapshot: dict[str, object]) -> WordPressSnapshotStatus:
    return WordPressSnapshotStatus(
        source_id=source.id,
        snapshot_id=uuid.UUID(str(snapshot["snapshot_id"])),
        status=str(snapshot.get("status") or "receiving"),
        accepted_batches=len(_list_value(snapshot.get("batches"))),
        accepted_pages=_int_value(snapshot.get("accepted_page_count")),
        ingestion_job_id=uuid.UUID(str(snapshot["ingestion_job_id"]))
        if snapshot.get("ingestion_job_id")
        else None,
        report_id=uuid.UUID(str(snapshot["report_id"])) if snapshot.get("report_id") else None,
    )


@router.get(
    "/service-visibility/sources/{source_id}/drafts",
    response_model=list[DraftProposalView],
)
async def get_approved_wordpress_drafts(
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> list[DraftProposalView]:
    source = await _bridge_source(source_id, session)
    await _authenticated_body(request, source=source, settings=settings)
    return [
        _draft_view(source, draft) for draft in _drafts(source) if draft.get("status") == "approved"
    ][:50]


@router.post(
    "/service-visibility/sources/{source_id}/drafts/{draft_id}/result",
    response_model=DraftProposalView,
)
async def record_wordpress_draft_result(
    source_id: uuid.UUID,
    draft_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> DraftProposalView:
    source = await _bridge_source(source_id, session)
    body = await _authenticated_body(request, source=source, settings=settings)
    payload = cast(DraftResultRequest, _parse_json(DraftResultRequest, body))
    drafts = _drafts(source)
    selected: dict[str, object] | None = None
    for draft in drafts:
        if draft.get("id") == str(draft_id):
            if draft.get("status") != "approved":
                raise ConflictError("Only approved draft proposals accept results")
            draft["status"] = payload.status
            draft["remote_draft_id"] = payload.remote_draft_id
            draft["error"] = payload.error
            draft["result_at"] = datetime.now(UTC).isoformat()
            selected = draft
            break
    if selected is None:
        raise HTTPException(status_code=404, detail="Draft proposal not found")
    source.config = {**dict(source.config), "draft_queue": drafts}
    await session.commit()
    return _draft_view(source, selected)
