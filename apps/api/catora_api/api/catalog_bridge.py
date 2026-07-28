from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from catora_api.catalog_bridge.security import CatalogBridgeAuthenticator
from catora_api.db.models import AuditEvent, Membership
from catora_api.db.models.catalog import CatalogSource, IngestionJob
from catora_api.schemas.catalog_bridge import (
    CATALOG_BRIDGE_PROTOCOL_VERSION,
    CatalogBridgeBatch,
    CatalogBridgeCompleteRequest,
    CatalogBridgeSnapshotManifest,
    CatalogBridgeSnapshotStatus,
    CatalogBridgeSourceCreateRequest,
    CatalogBridgeSourceProvisionResponse,
)
from catora_api.storage import ObjectStorage
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["catalog bridge"])
_ACTIVE_JOB_STATUSES = {"queued", "validating", "running"}
_TERMINAL_JOB_STATUSES = {"completed", "partially_completed", "failed", "cancelled"}


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


async def _locked_source(
    session: SessionDependency,
    source_id: uuid.UUID,
) -> CatalogSource:
    source = await session.scalar(
        select(CatalogSource)
        .where(
            CatalogSource.id == source_id,
            CatalogSource.source_type == "bridge",
            CatalogSource.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Catalog bridge source not found")
    return source


def _snapshot(source: CatalogSource) -> dict[str, Any]:
    value = source.config.get("bridge_snapshot")
    return dict(value) if isinstance(value, dict) else {}


def _batches(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    value = snapshot.get("batches")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _job_id(snapshot: dict[str, Any]) -> uuid.UUID | None:
    value = snapshot.get("ingestion_job_id")
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _status_view(
    session: SessionDependency,
    *,
    source: CatalogSource,
    snapshot: dict[str, Any],
) -> CatalogBridgeSnapshotStatus:
    snapshot_id_value = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id_value, str):
        raise HTTPException(status_code=404, detail="Catalog bridge snapshot not found")
    job_id = _job_id(snapshot)
    job = await session.get(IngestionJob, job_id) if job_id else None
    snapshot_status = str(snapshot.get("status") or "receiving")
    if job is not None:
        if job.status == "queued":
            snapshot_status = "queued"
        elif job.status in {"validating", "running"}:
            snapshot_status = "processing"
        elif job.status in {"completed", "partially_completed"}:
            snapshot_status = "completed"
        elif job.status in {"failed", "cancelled"}:
            snapshot_status = "failed"
    return CatalogBridgeSnapshotStatus(
        sourceId=source.id,
        snapshotId=uuid.UUID(snapshot_id_value),
        status=snapshot_status,
        acceptedBatches=len(_batches(snapshot)),
        acceptedProducts=int(snapshot.get("accepted_product_count") or 0),
        acceptedVariants=int(snapshot.get("accepted_variant_count") or 0),
        ingestionJobId=job_id,
    )


async def _authenticated_body(
    request: Request,
    *,
    source: CatalogSource,
    settings: SettingsDependency,
) -> bytes:
    if not settings.catalog_bridge_enabled:
        raise HTTPException(status_code=503, detail="Catalog bridge is disabled")
    body = await request.body()
    if len(body) > settings.catalog_bridge_max_batch_bytes:
        raise HTTPException(status_code=413, detail="Catalog bridge request is too large")
    await CatalogBridgeAuthenticator(settings).authenticate(
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


@router.post(
    "/workspaces/{workspace_id}/catalog-bridge/sources",
    response_model=CatalogBridgeSourceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_bridge_source(
    workspace_id: uuid.UUID,
    payload: CatalogBridgeSourceCreateRequest,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CatalogBridgeSourceProvisionResponse:
    if not settings.catalog_bridge_enabled:
        raise HTTPException(status_code=503, detail="Catalog bridge is disabled")
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type="bridge",
        status="ready",
        config={
            "protocol_version": CATALOG_BRIDGE_PROTOCOL_VERSION,
            "normalization_aliases": {},
        },
    )
    session.add(source)
    await session.flush()
    credential = CatalogBridgeAuthenticator(settings).rotate(source)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.bridge_source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={"token_fingerprint": credential.fingerprint},
        )
    )
    await session.commit()
    endpoint = str(request.base_url).rstrip("/")
    return CatalogBridgeSourceProvisionResponse(
        sourceId=source.id,
        endpoint=endpoint,
        token=credential.token,
        tokenFingerprint=credential.fingerprint,
        protocolVersion=CATALOG_BRIDGE_PROTOCOL_VERSION,
    )


@router.post(
    "/workspaces/{workspace_id}/catalog-bridge/sources/{source_id}/rotate",
    response_model=CatalogBridgeSourceProvisionResponse,
)
async def rotate_catalog_bridge_source(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CatalogBridgeSourceProvisionResponse:
    if not settings.catalog_bridge_enabled:
        raise HTTPException(status_code=503, detail="Catalog bridge is disabled")
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_write(membership.role)
    source = await session.scalar(
        select(CatalogSource)
        .where(
            CatalogSource.id == source_id,
            CatalogSource.workspace_id == workspace_id,
            CatalogSource.source_type == "bridge",
            CatalogSource.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Catalog bridge source not found")
    credential = CatalogBridgeAuthenticator(settings).rotate(source)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.bridge_credential_rotated",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={"token_fingerprint": credential.fingerprint},
        )
    )
    await session.commit()
    return CatalogBridgeSourceProvisionResponse(
        sourceId=source.id,
        endpoint=str(request.base_url).rstrip("/"),
        token=credential.token,
        tokenFingerprint=credential.fingerprint,
        protocolVersion=CATALOG_BRIDGE_PROTOCOL_VERSION,
    )


@router.post(
    "/catalog-bridge/sources/{source_id}/snapshots",
    response_model=CatalogBridgeSnapshotStatus,
)
async def begin_catalog_bridge_snapshot(
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> CatalogBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    manifest = cast(CatalogBridgeSnapshotManifest, _parse_json(CatalogBridgeSnapshotManifest, body))
    current = _snapshot(source)
    current_id = current.get("snapshot_id")
    if current_id == str(manifest.snapshot_id):
        if (
            current.get("declared_product_count") != manifest.declared_product_count
            or current.get("declared_variant_count") != manifest.declared_variant_count
        ):
            raise ConflictError("Catalog bridge snapshot manifest does not match the existing snapshot")
        return await _status_view(session, source=source, snapshot=current)
    current_job_id = _job_id(current)
    current_job = await session.get(IngestionJob, current_job_id) if current_job_id else None
    if current.get("status") == "receiving" or (
        current_job is not None and current_job.status in _ACTIVE_JOB_STATUSES
    ):
        raise ConflictError("A catalog bridge snapshot is already active")
    source.config = {
        **dict(source.config),
        "bridge_snapshot": {
            "protocol_version": manifest.protocol_version,
            "snapshot_id": str(manifest.snapshot_id),
            "started_at": manifest.started_at.isoformat(),
            "declared_product_count": manifest.declared_product_count,
            "declared_variant_count": manifest.declared_variant_count,
            "source_label": manifest.source_label,
            "metadata": manifest.metadata,
            "status": "receiving",
            "batches": [],
            "accepted_product_count": 0,
            "accepted_variant_count": 0,
            "ingestion_job_id": None,
        },
    }
    await session.commit()
    return await _status_view(session, source=source, snapshot=_snapshot(source))


@router.put(
    "/catalog-bridge/sources/{source_id}/snapshots/{snapshot_id}/batches/{sequence}",
    response_model=CatalogBridgeSnapshotStatus,
)
async def upload_catalog_bridge_batch(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    sequence: int,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    storage: StorageDependency,
) -> CatalogBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    batch = cast(CatalogBridgeBatch, _parse_json(CatalogBridgeBatch, body))
    if batch.snapshot_id != snapshot_id or batch.sequence != sequence:
        raise ConflictError("Catalog bridge batch path does not match its payload")
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Catalog bridge snapshot not found")
    if snapshot.get("status") != "receiving":
        raise ConflictError("Catalog bridge snapshot is not accepting batches")
    batches = _batches(snapshot)
    checksum = hashlib.sha256(body).hexdigest()
    if sequence < len(batches):
        existing = batches[sequence]
        if existing.get("checksum") != checksum:
            raise ConflictError("Catalog bridge batch sequence was already used")
        return await _status_view(session, source=source, snapshot=snapshot)
    if sequence != len(batches):
        raise ConflictError("Catalog bridge batches must be uploaded in sequence")
    object_key = (
        f"workspaces/{source.workspace_id}/catalog-bridge/{source.id}/"
        f"{snapshot_id}/{sequence:08d}.json"
    )
    stored = await storage.put_bytes(object_key, body, content_type="application/json")
    product_count = len(batch.records)
    variant_count = sum(len(product.variants) for product in batch.records)
    batches.append(
        {
            "sequence": sequence,
            "object_key": stored.key,
            "checksum": checksum,
            "size_bytes": stored.size_bytes,
            "product_count": product_count,
            "variant_count": variant_count,
        }
    )
    snapshot.update(
        {
            "batches": batches,
            "accepted_product_count": int(snapshot.get("accepted_product_count") or 0)
            + product_count,
            "accepted_variant_count": int(snapshot.get("accepted_variant_count") or 0)
            + variant_count,
        }
    )
    source.config = {**dict(source.config), "bridge_snapshot": snapshot}
    await session.commit()
    return await _status_view(session, source=source, snapshot=snapshot)


@router.post(
    "/catalog-bridge/sources/{source_id}/snapshots/{snapshot_id}/complete",
    response_model=CatalogBridgeSnapshotStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_catalog_bridge_snapshot(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> CatalogBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    complete = cast(
        CatalogBridgeCompleteRequest,
        _parse_json(CatalogBridgeCompleteRequest, body),
    )
    if complete.snapshot_id != snapshot_id:
        raise ConflictError("Catalog bridge completion path does not match its payload")
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Catalog bridge snapshot not found")
    existing_job_id = _job_id(snapshot)
    if existing_job_id is not None:
        return await _status_view(session, source=source, snapshot=snapshot)
    batches = _batches(snapshot)
    accepted_products = int(snapshot.get("accepted_product_count") or 0)
    accepted_variants = int(snapshot.get("accepted_variant_count") or 0)
    declared_products = int(snapshot.get("declared_product_count") or 0)
    declared_variants = int(snapshot.get("declared_variant_count") or 0)
    if (
        complete.batch_count != len(batches)
        or complete.product_count != accepted_products
        or complete.variant_count != accepted_variants
        or declared_products != accepted_products
        or declared_variants != accepted_variants
    ):
        raise ConflictError("Catalog bridge snapshot counts do not reconcile")
    job = IngestionJob(
        workspace_id=source.workspace_id,
        catalog_source_id=source.id,
        status="queued",
        checkpoint={"bridge_snapshot_id": str(snapshot_id)},
    )
    session.add(job)
    await session.flush()
    snapshot.update(
        {
            "status": "complete",
            "ingestion_job_id": str(job.id),
        }
    )
    source.config = {**dict(source.config), "bridge_snapshot": snapshot}
    source.status = "ready"
    session.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=None,
            event_type="catalog.bridge_snapshot_queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            payload={
                "catalog_source_id": str(source.id),
                "snapshot_id": str(snapshot_id),
                "product_count": accepted_products,
                "variant_count": accepted_variants,
                "batch_count": len(batches),
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task("catora.ingestion.run", args=[str(job.id)])
    except Exception as exc:
        job.status = "failed"
        job.checkpoint = {
            **dict(job.checkpoint),
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue catalog bridge ingestion",
        }
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Unable to enqueue catalog bridge ingestion",
        ) from exc
    return await _status_view(session, source=source, snapshot=snapshot)


@router.get(
    "/catalog-bridge/sources/{source_id}/snapshots/{snapshot_id}",
    response_model=CatalogBridgeSnapshotStatus,
)
async def get_catalog_bridge_snapshot(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> CatalogBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    await _authenticated_body(request, source=source, settings=settings)
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Catalog bridge snapshot not found")
    return await _status_view(session, source=source, snapshot=snapshot)
