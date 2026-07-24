from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, status

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import ReportJob, ShopifyStoreInvitation
from catora_api.schemas.shopify_public import (
    ShopifyBulkOperationStatus,
    ShopifyPublicActivationView,
    ShopifyPublicInstallationStatus,
    ShopifyPublicInstallationView,
    ShopifyPublicSessionView,
    ShopifyPublicSyncStatus,
    ShopifyStoreInvitationCreateRequest,
    ShopifyStoreInvitationView,
)
from catora_api.shopify.invitations import (
    ShopifyInvitationError,
    ShopifyInvitationService,
)
from catora_api.shopify.public_installations import (
    ShopifyPublicInstallationError,
    ShopifyPublicInstallationService,
)
from catora_api.shopify.public_session import (
    ShopifyPublicSession,
    ShopifyPublicTokenExchange,
    ShopifyPublicTokenExchangeError,
    bearer_session_token,
    verify_shopify_public_session_token,
)
from catora_api.shopify.sync import queue_shopify_sync

router = APIRouter(tags=["shopify public app invitations"])


def _require_source_management(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


def _snapshot_text(snapshot: dict[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _snapshot_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _snapshot_bool(snapshot: dict[str, object], key: str) -> bool:
    return snapshot.get(key) is True


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


def _authenticated_shopify_session(
    request: Request,
    settings: SettingsDependency,
) -> tuple[str, ShopifyPublicSession]:
    if not settings.shopify_public_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The Catora Shopify public app is not configured",
        )
    try:
        settings.validate_shopify_public()
        token = bearer_session_token(request.headers.get("authorization"))
        shopify_session = verify_shopify_public_session_token(
            token,
            client_id=settings.shopify_public_client_id,
            client_secret=settings.shopify_public_client_secret,
            clock_skew_seconds=settings.shopify_public_session_clock_skew_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Shopify session could not be authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return token, shopify_session


async def _invitation_for_session(
    session: SessionDependency,
    shopify_session: ShopifyPublicSession,
) -> ShopifyStoreInvitation:
    try:
        return await ShopifyInvitationService().require_activatable(
            session,
            shop_domain=shopify_session.shop_domain,
        )
    except ShopifyInvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


async def _installation_for_invitation(
    session: SessionDependency,
    settings: SettingsDependency,
    invitation: ShopifyStoreInvitation,
) -> ReportJob:
    workspace_id = invitation.activated_workspace_id
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The invited Shopify store has not been activated",
        )
    installation = await ShopifyPublicInstallationService(settings).find_installation(
        session,
        workspace_id=workspace_id,
        shop_domain=invitation.shop_domain,
    )
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The Shopify public installation was not found",
        )
    return installation


def _installation_view(
    installation: ReportJob,
    invitation: ShopifyStoreInvitation,
) -> ShopifyPublicInstallationView:
    snapshot = dict(installation.input_snapshot)
    status_value = installation.status
    if status_value not in {
        "active",
        "refresh_required",
        "disconnected",
        "failed",
    }:
        status_value = "failed"
    installation_status = cast(ShopifyPublicInstallationStatus, status_value)

    sync_value = _snapshot_text(snapshot, "sync_status") or "not_started"
    if sync_value not in {
        "not_started",
        "queued",
        "coalesced",
        "running",
        "completed",
        "failed",
    }:
        sync_value = "failed"
    sync_status = cast(ShopifyPublicSyncStatus, sync_value)

    bulk_value = _snapshot_text(snapshot, "last_bulk_operation_status")
    if bulk_value not in {"canceled", "canceling", "completed", "failed"}:
        bulk_value = None
    bulk_status = cast(ShopifyBulkOperationStatus | None, bulk_value)

    feature_tier = cast(
        Literal["demo", "plus_demo"],
        invitation.feature_tier,
    )
    return ShopifyPublicInstallationView(
        shop_domain=invitation.shop_domain,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        installation_id=installation.id,
        catalog_source_id=_snapshot_uuid(snapshot, "catalog_source_id"),
        feature_tier=feature_tier,
        installation_status=installation_status,
        sync_status=sync_status,
        product_count=_snapshot_int(snapshot, "product_count"),
        variant_count=_snapshot_int(snapshot, "variant_count"),
        warning_count=_snapshot_int(snapshot, "warning_count"),
        assigned_category_count=_snapshot_int(snapshot, "assigned_category_count"),
        ambiguous_category_count=_snapshot_int(snapshot, "ambiguous_category_count"),
        unclassified_category_count=_snapshot_int(
            snapshot,
            "unclassified_category_count",
        ),
        last_successful_sync_at=_snapshot_datetime(
            snapshot,
            "last_successful_sync_at",
        ),
        last_sync_job_id=_snapshot_uuid(snapshot, "last_sync_job_id"),
        last_audit_run_id=_snapshot_uuid(snapshot, "last_audit_run_id"),
        last_sync_error_type=_snapshot_text(snapshot, "last_sync_error_type"),
        last_sync_full_reconciliation=_snapshot_bool(
            snapshot,
            "last_sync_full_reconciliation",
        ),
        last_completed_full_reconciliation=_snapshot_bool(
            snapshot,
            "last_completed_full_reconciliation",
        ),
        last_bulk_operation_status=bulk_status,
        last_bulk_operation_completed_at=_snapshot_datetime(
            snapshot,
            "last_bulk_operation_completed_at",
        ),
        last_bulk_webhook_received_at=_snapshot_datetime(
            snapshot,
            "last_bulk_webhook_received_at",
        ),
        last_bulk_operation_error_code=_snapshot_text(
            snapshot,
            "last_bulk_operation_error_code",
        ),
        reauthorization_required=installation_status == "refresh_required",
    )


@router.get(
    "/shopify/public/session",
    response_model=ShopifyPublicSessionView,
)
async def authenticate_shopify_public_session(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyPublicSessionView:
    _, shopify_session = _authenticated_shopify_session(request, settings)
    invitation = await _invitation_for_session(session, shopify_session)

    invitation_status = cast(
        Literal["pending", "activated"],
        invitation.status,
    )
    feature_tier = cast(
        Literal["demo", "plus_demo"],
        invitation.feature_tier,
    )
    return ShopifyPublicSessionView(
        shop_domain=shopify_session.shop_domain,
        shopify_user_id=shopify_session.user_id,
        invitation_status=invitation_status,
        feature_tier=feature_tier,
        invitation_expires_at=invitation.expires_at,
        activated_workspace_id=invitation.activated_workspace_id,
        session_expires_at=shopify_session.expires_at,
    )


@router.post(
    "/shopify/public/activate",
    response_model=ShopifyPublicActivationView,
)
async def activate_shopify_public_installation(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyPublicActivationView:
    session_token, shopify_session = _authenticated_shopify_session(request, settings)
    invitation = await _invitation_for_session(session, shopify_session)
    try:
        token_bundle = await ShopifyPublicTokenExchange(settings).exchange(
            session_token=session_token,
            session=shopify_session,
        )
    except ShopifyPublicTokenExchangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shopify could not complete the public app credential exchange",
        ) from exc

    try:
        activation = await ShopifyPublicInstallationService(settings).activate(
            session,
            invitation=invitation,
            shopify_session=shopify_session,
            token_bundle=token_bundle,
        )
    except ShopifyPublicInstallationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    snapshot = dict(activation.installation.input_snapshot)
    ingestion_job = None
    if activation.created or not snapshot.get("last_sync_job_id"):
        ingestion_job = await queue_shopify_sync(
            session,
            installation=activation.installation,
            reason="public_app_activation",
        )
        snapshot = dict(activation.installation.input_snapshot)

    sync_status = cast(
        ShopifyPublicSyncStatus,
        snapshot.get("sync_status") or "not_started",
    )
    feature_tier = cast(
        Literal["demo", "plus_demo"],
        activation.feature_tier,
    )
    return ShopifyPublicActivationView(
        shop_domain=shopify_session.shop_domain,
        workspace_id=activation.workspace_id,
        installation_id=activation.installation.id,
        catalog_source_id=activation.catalog_source.id,
        ingestion_job_id=ingestion_job.id if ingestion_job is not None else None,
        feature_tier=feature_tier,
        sync_status=sync_status,
        created=activation.created,
    )


@router.get(
    "/shopify/public/installation",
    response_model=ShopifyPublicInstallationView,
)
async def get_shopify_public_installation(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyPublicInstallationView:
    _, shopify_session = _authenticated_shopify_session(request, settings)
    invitation = await _invitation_for_session(session, shopify_session)
    installation = await _installation_for_invitation(session, settings, invitation)
    return _installation_view(installation, invitation)


@router.post(
    "/shopify/public/installation/sync",
    response_model=ShopifyPublicInstallationView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_shopify_public_installation(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyPublicInstallationView:
    _, shopify_session = _authenticated_shopify_session(request, settings)
    invitation = await _invitation_for_session(session, shopify_session)
    installation = await _installation_for_invitation(session, settings, invitation)
    if installation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Shopify public installation requires reauthorization",
        )
    job = await queue_shopify_sync(
        session,
        installation=installation,
        reason="embedded_app_manual",
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shopify synchronization is unavailable",
        )
    await session.refresh(installation)
    return _installation_view(installation, invitation)


@router.post(
    "/workspaces/{workspace_id}/shopify/public-invitations",
    response_model=ShopifyStoreInvitationView,
    status_code=status.HTTP_201_CREATED,
)
async def create_shopify_public_invitation(
    workspace_id: uuid.UUID,
    payload: ShopifyStoreInvitationCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyStoreInvitationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    try:
        invitation = await ShopifyInvitationService().create_or_replace(
            session,
            issuer_workspace_id=workspace_id,
            actor_user_id=context.user.id,
            shop_domain=payload.shop_domain,
            prospect_name=payload.prospect_name,
            expires_in_hours=payload.expires_in_hours,
            feature_tier=payload.feature_tier,
        )
    except ShopifyInvitationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ShopifyStoreInvitationView.model_validate(invitation)


@router.get(
    "/workspaces/{workspace_id}/shopify/public-invitations",
    response_model=list[ShopifyStoreInvitationView],
)
async def list_shopify_public_invitations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[ShopifyStoreInvitationView]:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    invitations = await ShopifyInvitationService().list_for_workspace(
        session,
        issuer_workspace_id=workspace_id,
    )
    return [ShopifyStoreInvitationView.model_validate(item) for item in invitations]


@router.delete(
    "/workspaces/{workspace_id}/shopify/public-invitations/{invitation_id}",
    response_model=ShopifyStoreInvitationView,
)
async def revoke_shopify_public_invitation(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyStoreInvitationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    try:
        invitation = await ShopifyInvitationService().revoke(
            session,
            issuer_workspace_id=workspace_id,
            invitation_id=invitation_id,
            actor_user_id=context.user.id,
        )
    except ShopifyInvitationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ShopifyStoreInvitationView.model_validate(invitation)
