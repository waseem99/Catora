from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent, ReportJob
from catora_api.db.models.catalog import CatalogSource
from catora_api.schemas.ingestion import (
    CatalogSourceView,
    ShopifySourceCreateRequest,
)
from catora_api.schemas.shopify_installations import (
    InstallationHealth,
    InstallationStatus,
    ShopifyConfigurationView,
    ShopifyInstallationView,
    ShopifyInstallStartRequest,
    ShopifyInstallStartResponse,
    ShopifyWebhookResponse,
    SyncStatus,
    TokenMode,
)
from catora_api.shopify.installations import (
    ShopifyCredentialError,
    ShopifyInstallationError,
    ShopifyInstallationService,
)
from catora_api.shopify.sync import queue_shopify_sync
from catora_api.shopify.webhooks import (
    ShopifyWebhookError,
    receive_shopify_webhook,
)

router = APIRouter(prefix="/api/v1", tags=["shopify catalog ingestion"])
OAUTH_COOKIE = "catora_shopify_oauth"


def _require_source_management(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


def _snapshot_text(snapshot: dict[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = _snapshot_text(snapshot, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _snapshot_datetime(snapshot: dict[str, object], key: str) -> datetime | None:
    value = _snapshot_text(snapshot, key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snapshot_scopes(snapshot: dict[str, object]) -> list[str]:
    value = snapshot.get("granted_scopes")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _snapshot_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def _installation_view(installation: ReportJob) -> ShopifyInstallationView:
    snapshot = dict(installation.input_snapshot)
    access_expires_at = _snapshot_datetime(snapshot, "access_token_expires_at")
    refresh_expires_at = _snapshot_datetime(snapshot, "refresh_token_expires_at")
    health: InstallationHealth
    if installation.status == "active":
        health = "healthy"
        detail = "Catora can resolve a protected Shopify catalog credential."
        if refresh_expires_at is not None and refresh_expires_at <= datetime.now(UTC):
            health = "refresh_required"
            detail = "The Shopify refresh token expired; reconnect the shop."
    elif installation.status == "refresh_required":
        health = "refresh_required"
        detail = "Shopify reauthorization is required."
    elif installation.status in {"disconnected", "revoked"}:
        health = "disconnected"
        detail = "The shop is disconnected and no credential is available."
    else:
        health = "unknown"
        detail = "The Shopify connection is not ready."

    status_value = installation.status
    if status_value not in {
        "pending",
        "active",
        "refresh_required",
        "disconnected",
        "revoked",
        "failed",
    }:
        status_value = "failed"
    installation_status = cast(InstallationStatus, status_value)

    token_mode_value = _snapshot_text(snapshot, "token_mode")
    if token_mode_value not in {"expiring_offline", "non_expiring_offline"}:
        token_mode_value = "expiring_offline"
    token_mode = cast(TokenMode, token_mode_value)

    sync_status_value = _snapshot_text(snapshot, "sync_status") or "not_started"
    if sync_status_value not in {
        "not_started",
        "queued",
        "coalesced",
        "running",
        "completed",
        "failed",
        "revoked",
    }:
        sync_status_value = "failed"
    sync_status = cast(SyncStatus, sync_status_value)

    return ShopifyInstallationView(
        id=installation.id,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        catalog_source_id=_snapshot_uuid(snapshot, "catalog_source_id"),
        shop_domain=_snapshot_text(snapshot, "shop_domain") or "unknown.myshopify.com",
        status=installation_status,
        granted_scopes=_snapshot_scopes(snapshot),
        token_mode=token_mode,
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        installed_at=_snapshot_datetime(snapshot, "installed_at"),
        refreshed_at=_snapshot_datetime(snapshot, "refreshed_at"),
        disconnected_at=_snapshot_datetime(snapshot, "disconnected_at"),
        last_health_checked_at=_snapshot_datetime(snapshot, "last_health_checked_at"),
        health=health,
        detail=detail,
        sync_status=sync_status,
        last_successful_sync_at=_snapshot_datetime(snapshot, "last_successful_sync_at"),
        last_sync_job_id=_snapshot_uuid(snapshot, "last_sync_job_id"),
        last_audit_run_id=_snapshot_uuid(snapshot, "last_audit_run_id"),
        product_count=_snapshot_int(snapshot, "product_count"),
        variant_count=_snapshot_int(snapshot, "variant_count"),
        warning_count=_snapshot_int(snapshot, "warning_count"),
        last_sync_error_type=_snapshot_text(snapshot, "last_sync_error_type"),
    )


@router.post(
    "/shopify/webhooks",
    response_model=ShopifyWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def accept_shopify_webhook(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyWebhookResponse:
    if not settings.shopify_enabled:
        raise HTTPException(status_code=503, detail="Shopify integration is disabled")
    body = await request.body()
    try:
        receipt = await receive_shopify_webhook(
            session,
            settings=settings,
            body=body,
            topic=request.headers.get("x-shopify-topic", ""),
            shop_domain=request.headers.get("x-shopify-shop-domain", ""),
            webhook_id=request.headers.get("x-shopify-webhook-id", ""),
            event_id=request.headers.get("x-shopify-event-id"),
            triggered_at=request.headers.get("x-shopify-triggered-at"),
            supplied_signature=request.headers.get("x-shopify-hmac-sha256", ""),
        )
    except ShopifyWebhookError as exc:
        code = 401 if "signature" in str(exc).casefold() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return ShopifyWebhookResponse(
        duplicate=receipt.duplicate,
        delivery_id=receipt.delivery_id,
    )


@router.get(
    "/workspaces/{workspace_id}/shopify/configuration",
    response_model=ShopifyConfigurationView,
)
async def get_shopify_configuration(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ShopifyConfigurationView:
    await auth_service.membership(session, context.user.id, workspace_id)
    return ShopifyConfigurationView(
        enabled=settings.shopify_enabled,
        required_scopes=list(settings.shopify_required_scopes),
        callback_url=settings.shopify_callback_url if settings.shopify_enabled else None,
    )


@router.post(
    "/workspaces/{workspace_id}/shopify/installations/start",
    response_model=ShopifyInstallStartResponse,
)
async def start_shopify_installation(
    workspace_id: uuid.UUID,
    payload: ShopifyInstallStartRequest,
    response: Response,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyInstallStartResponse:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    try:
        authorization_url, state, expires_at = await ShopifyInstallationService(
            settings
        ).start(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            shop_domain=payload.shop_domain,
        )
    except ShopifyInstallationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.set_cookie(
        OAUTH_COOKIE,
        state,
        max_age=settings.shopify_oauth_state_ttl_minutes * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/api/v1/shopify/oauth/callback",
    )
    return ShopifyInstallStartResponse(
        authorization_url=authorization_url,
        expires_at=expires_at,
    )


@router.get("/shopify/oauth/callback", include_in_schema=False)
async def complete_shopify_installation(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RedirectResponse:
    service = ShopifyInstallationService(settings)
    state_cookie = request.cookies.get(OAUTH_COOKIE)
    try:
        installation = await service.complete_callback(
            session,
            query_items=list(request.query_params.multi_items()),
            state_cookie=state_cookie,
        )
        await queue_shopify_sync(
            session,
            installation=installation,
            reason="initial_install",
        )
        target = (
            f"{settings.frontend_url}/workspace/{installation.workspace_id}/onboarding?"
            + urlencode(
                {
                    "shopify": "connected",
                    "installation_id": str(installation.id),
                }
            )
        )
    except (ShopifyInstallationError, ValueError):
        target = f"{settings.frontend_url}/workspaces?shopify=error"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OAUTH_COOKIE, path="/api/v1/shopify/oauth/callback")
    return response


@router.get(
    "/workspaces/{workspace_id}/shopify/installation",
    response_model=ShopifyInstallationView | None,
)
async def get_shopify_installation(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ShopifyInstallationView | None:
    await auth_service.membership(session, context.user.id, workspace_id)
    installation = await ShopifyInstallationService().find_installation(
        session,
        workspace_id=workspace_id,
    )
    return _installation_view(installation) if installation is not None else None


@router.post(
    "/workspaces/{workspace_id}/shopify/installation/sync",
    response_model=ShopifyInstallationView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_shopify_installation(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyInstallationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    service = ShopifyInstallationService()
    installation = await service.find_installation(session, workspace_id=workspace_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Shopify installation not found")
    job = await queue_shopify_sync(
        session,
        installation=installation,
        reason="manual",
        actor_user_id=context.user.id,
    )
    if job is None:
        raise HTTPException(status_code=409, detail="Shopify synchronization is unavailable")
    await session.refresh(installation)
    return _installation_view(installation)


@router.post(
    "/workspaces/{workspace_id}/shopify/installation/refresh",
    response_model=ShopifyInstallationView,
)
async def refresh_shopify_installation(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyInstallationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    service = ShopifyInstallationService()
    installation = await service.find_installation(session, workspace_id=workspace_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Shopify installation not found")
    try:
        await service.resolve_access_token(installation.id)
    except ShopifyCredentialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.refresh(installation)
    return _installation_view(installation)


@router.delete(
    "/workspaces/{workspace_id}/shopify/installation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_shopify_installation(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> None:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    service = ShopifyInstallationService()
    installation = await service.find_installation(session, workspace_id=workspace_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Shopify installation not found")
    await service.disconnect(
        session,
        installation=installation,
        actor_user_id=context.user.id,
    )


@router.post(
    "/workspaces/{workspace_id}/shopify-catalog-sources",
    response_model=CatalogSourceView,
    status_code=status.HTTP_201_CREATED,
)
async def create_shopify_catalog_source(
    workspace_id: uuid.UUID,
    payload: ShopifySourceCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CatalogSourceView:
    membership = await auth_service.membership(
        session,
        context.user.id,
        workspace_id,
    )
    _require_source_management(membership.role)

    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type="shopify",
        status="draft",
        credential_ref=payload.credential_ref,
        config={
            "shop_domain": payload.shop_domain,
            "api_version": payload.api_version,
            "updated_after": payload.updated_after.isoformat()
            if payload.updated_after is not None
            else None,
            "normalization_aliases": payload.normalization_aliases.model_dump(),
        },
    )
    session.add(source)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.shopify_source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={
                "source_type": "shopify",
                "name": source.name,
                "shop_domain": payload.shop_domain,
                "api_version": payload.api_version,
                "normalization_alias_groups": [
                    key
                    for key, values in payload.normalization_aliases.model_dump().items()
                    if values
                ],
            },
        )
    )
    await session.commit()
    await session.refresh(source)
    return CatalogSourceView.model_validate(source)
