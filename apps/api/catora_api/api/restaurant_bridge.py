from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import HttpUrl, ValidationError
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
from catora_api.schemas.catalog_bridge import CATALOG_BRIDGE_PROTOCOL_VERSION
from catora_api.schemas.restaurant_bridge import (
    RESTAURANT_BRIDGE_PROFILE,
    RestaurantBridgeBatch,
    RestaurantBridgeCompleteRequest,
    RestaurantBridgeSnapshotManifest,
    RestaurantBridgeSnapshotStatus,
    RestaurantBridgeSourceCreateRequest,
    RestaurantBridgeSourceProvisionResponse,
)
from catora_api.storage import ObjectStorage
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["restaurant bridge"])
_ACTIVE_JOB_STATUSES = {"queued", "validating", "running"}


def get_object_storage(settings: SettingsDependency) -> ObjectStorage:
    return ObjectStorage(settings)


StorageDependency = Annotated[ObjectStorage, Depends(get_object_storage)]


def _require_enabled(settings: SettingsDependency) -> None:
    if not settings.catalog_bridge_enabled:
        raise HTTPException(status_code=503, detail="Catalog bridge is disabled")
    if not settings.restaurant_domain_enabled:
        raise HTTPException(status_code=503, detail="Restaurant domain is disabled")


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


def _profile(source: CatalogSource) -> str:
    value = source.config.get("profile")
    return value if isinstance(value, str) else "catalog/v1"


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
    if source is None or _profile(source) != RESTAURANT_BRIDGE_PROFILE:
        raise HTTPException(status_code=404, detail="Restaurant bridge source not found")
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
) -> RestaurantBridgeSnapshotStatus:
    snapshot_id_value = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id_value, str):
        raise HTTPException(status_code=404, detail="Restaurant bridge snapshot not found")
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
    return RestaurantBridgeSnapshotStatus(
        sourceId=source.id,
        snapshotId=uuid.UUID(snapshot_id_value),
        status=snapshot_status,
        acceptedBatches=len(_batches(snapshot)),
        acceptedBrands=int(snapshot.get("accepted_brand_count") or 0),
        acceptedLocations=int(snapshot.get("accepted_location_count") or 0),
        acceptedMenuItems=int(snapshot.get("accepted_menu_item_count") or 0),
        ingestionJobId=job_id,
    )


async def _authenticated_body(
    request: Request,
    *,
    source: CatalogSource,
    settings: SettingsDependency,
) -> bytes:
    _require_enabled(settings)
    body = await request.body()
    if len(body) > settings.catalog_bridge_max_batch_bytes:
        raise HTTPException(status_code=413, detail="Restaurant bridge request is too large")
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


def _nested_counts(batch: RestaurantBridgeBatch) -> tuple[int, int, int]:
    brands = len(batch.records)
    locations = sum(len(brand.locations) for brand in batch.records)
    menu_items = sum(
        len(section.items)
        for brand in batch.records
        for location in brand.locations
        for menu in location.menus
        for section in menu.sections
    )
    return brands, locations, menu_items


@router.post(
    "/workspaces/{workspace_id}/restaurant-bridge/sources",
    response_model=RestaurantBridgeSourceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_restaurant_bridge_source(
    workspace_id: uuid.UUID,
    payload: RestaurantBridgeSourceCreateRequest,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> RestaurantBridgeSourceProvisionResponse:
    _require_enabled(settings)
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
            "profile": RESTAURANT_BRIDGE_PROFILE,
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
            event_type="restaurant.bridge_source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={
                "profile": RESTAURANT_BRIDGE_PROFILE,
                "token_fingerprint": credential.fingerprint,
            },
        )
    )
    await session.commit()
    return RestaurantBridgeSourceProvisionResponse(
        sourceId=source.id,
        endpoint=HttpUrl(str(request.base_url).rstrip("/")),
        token=credential.token,
        tokenFingerprint=credential.fingerprint,
        protocolVersion=CATALOG_BRIDGE_PROTOCOL_VERSION,
        profile=RESTAURANT_BRIDGE_PROFILE,
    )


@router.post(
    "/restaurant-bridge/sources/{source_id}/snapshots",
    response_model=RestaurantBridgeSnapshotStatus,
)
async def begin_restaurant_bridge_snapshot(
    source_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RestaurantBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    manifest = cast(
        RestaurantBridgeSnapshotManifest,
        _parse_json(RestaurantBridgeSnapshotManifest, body),
    )
    current = _snapshot(source)
    if current.get("snapshot_id") == str(manifest.snapshot_id):
        if (
            current.get("declared_brand_count") != manifest.declared_brand_count
            or current.get("declared_location_count") != manifest.declared_location_count
            or current.get("declared_menu_item_count") != manifest.declared_menu_item_count
        ):
            raise ConflictError(
                "Restaurant bridge snapshot manifest does not match the existing snapshot"
            )
        return await _status_view(session, source=source, snapshot=current)
    current_job_id = _job_id(current)
    current_job = await session.get(IngestionJob, current_job_id) if current_job_id else None
    if current.get("status") == "receiving" or (
        current_job is not None and current_job.status in _ACTIVE_JOB_STATUSES
    ):
        raise ConflictError("A restaurant bridge snapshot is already active")
    source.config = {
        **dict(source.config),
        "bridge_snapshot": {
            "protocol_version": manifest.protocol_version,
            "profile": RESTAURANT_BRIDGE_PROFILE,
            "snapshot_id": str(manifest.snapshot_id),
            "started_at": manifest.started_at.isoformat(),
            "declared_brand_count": manifest.declared_brand_count,
            "declared_location_count": manifest.declared_location_count,
            "declared_menu_item_count": manifest.declared_menu_item_count,
            "source_label": manifest.source_label,
            "metadata": manifest.metadata,
            "status": "receiving",
            "batches": [],
            "accepted_brand_count": 0,
            "accepted_location_count": 0,
            "accepted_menu_item_count": 0,
            "ingestion_job_id": None,
        },
    }
    await session.commit()
    return await _status_view(session, source=source, snapshot=_snapshot(source))


@router.put(
    "/restaurant-bridge/sources/{source_id}/snapshots/{snapshot_id}/batches/{sequence}",
    response_model=RestaurantBridgeSnapshotStatus,
)
async def upload_restaurant_bridge_batch(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    sequence: int,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    storage: StorageDependency,
) -> RestaurantBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    batch = cast(RestaurantBridgeBatch, _parse_json(RestaurantBridgeBatch, body))
    if batch.snapshot_id != snapshot_id or batch.sequence != sequence:
        raise ConflictError("Restaurant bridge batch path does not match its payload")
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Restaurant bridge snapshot not found")
    if snapshot.get("status") != "receiving":
        raise ConflictError("Restaurant bridge snapshot is not accepting batches")
    batches = _batches(snapshot)
    checksum = hashlib.sha256(body).hexdigest()
    if sequence < len(batches):
        if batches[sequence].get("checksum") != checksum:
            raise ConflictError("Restaurant bridge batch sequence was already used")
        return await _status_view(session, source=source, snapshot=snapshot)
    if sequence != len(batches):
        raise ConflictError("Restaurant bridge batches must be uploaded in sequence")
    object_key = (
        f"workspaces/{source.workspace_id}/catalog-bridge/{source.id}/"
        f"{snapshot_id}/{sequence:08d}.json"
    )
    stored = await storage.put_bytes(object_key, body, content_type="application/json")
    brand_count, location_count, menu_item_count = _nested_counts(batch)
    batches.append(
        {
            "sequence": sequence,
            "object_key": stored.key,
            "checksum": checksum,
            "size_bytes": stored.size_bytes,
            "brand_count": brand_count,
            "location_count": location_count,
            "menu_item_count": menu_item_count,
        }
    )
    snapshot.update(
        {
            "batches": batches,
            "accepted_brand_count": int(snapshot.get("accepted_brand_count") or 0)
            + brand_count,
            "accepted_location_count": int(snapshot.get("accepted_location_count") or 0)
            + location_count,
            "accepted_menu_item_count": int(snapshot.get("accepted_menu_item_count") or 0)
            + menu_item_count,
        }
    )
    source.config = {**dict(source.config), "bridge_snapshot": snapshot}
    await session.commit()
    return await _status_view(session, source=source, snapshot=snapshot)


@router.post(
    "/restaurant-bridge/sources/{source_id}/snapshots/{snapshot_id}/complete",
    response_model=RestaurantBridgeSnapshotStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_restaurant_bridge_snapshot(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RestaurantBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    body = await _authenticated_body(request, source=source, settings=settings)
    complete = cast(
        RestaurantBridgeCompleteRequest,
        _parse_json(RestaurantBridgeCompleteRequest, body),
    )
    if complete.snapshot_id != snapshot_id:
        raise ConflictError("Restaurant bridge completion path does not match its payload")
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Restaurant bridge snapshot not found")
    existing_job_id = _job_id(snapshot)
    if existing_job_id is not None:
        return await _status_view(session, source=source, snapshot=snapshot)
    batches = _batches(snapshot)
    accepted_brands = int(snapshot.get("accepted_brand_count") or 0)
    accepted_locations = int(snapshot.get("accepted_location_count") or 0)
    accepted_menu_items = int(snapshot.get("accepted_menu_item_count") or 0)
    if (
        complete.batch_count != len(batches)
        or complete.brand_count != accepted_brands
        or complete.location_count != accepted_locations
        or complete.menu_item_count != accepted_menu_items
        or int(snapshot.get("declared_brand_count") or 0) != accepted_brands
        or int(snapshot.get("declared_location_count") or 0) != accepted_locations
        or int(snapshot.get("declared_menu_item_count") or 0) != accepted_menu_items
    ):
        raise ConflictError("Restaurant bridge snapshot counts do not reconcile")
    job = IngestionJob(
        workspace_id=source.workspace_id,
        catalog_source_id=source.id,
        status="queued",
        checkpoint={
            "bridge_snapshot_id": str(snapshot_id),
            "bridge_profile": RESTAURANT_BRIDGE_PROFILE,
        },
    )
    session.add(job)
    await session.flush()
    snapshot.update({"status": "complete", "ingestion_job_id": str(job.id)})
    source.config = {**dict(source.config), "bridge_snapshot": snapshot}
    source.status = "ready"
    session.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=None,
            event_type="restaurant.bridge_snapshot_queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            payload={
                "catalog_source_id": str(source.id),
                "snapshot_id": str(snapshot_id),
                "brand_count": accepted_brands,
                "location_count": accepted_locations,
                "menu_item_count": accepted_menu_items,
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
            "error_message": "Unable to enqueue restaurant bridge ingestion",
        }
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Unable to enqueue restaurant bridge ingestion",
        ) from exc
    return await _status_view(session, source=source, snapshot=snapshot)


@router.get(
    "/restaurant-bridge/sources/{source_id}/snapshots/{snapshot_id}",
    response_model=RestaurantBridgeSnapshotStatus,
)
async def get_restaurant_bridge_snapshot(
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RestaurantBridgeSnapshotStatus:
    source = await _locked_source(session, source_id)
    await _authenticated_body(request, source=source, settings=settings)
    snapshot = _snapshot(source)
    if snapshot.get("snapshot_id") != str(snapshot_id):
        raise HTTPException(status_code=404, detail="Restaurant bridge snapshot not found")
    return await _status_view(session, source=source, snapshot=snapshot)
