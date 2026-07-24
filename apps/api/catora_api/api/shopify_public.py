from __future__ import annotations

import uuid
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
from catora_api.schemas.shopify_public import (
    ShopifyPublicSessionView,
    ShopifyStoreInvitationCreateRequest,
    ShopifyStoreInvitationView,
)
from catora_api.shopify.invitations import (
    ShopifyInvitationError,
    ShopifyInvitationService,
)
from catora_api.shopify.public_session import (
    bearer_session_token,
    verify_shopify_public_session_token,
)

router = APIRouter(tags=["shopify public app invitations"])


def _require_source_management(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


@router.get(
    "/shopify/public/session",
    response_model=ShopifyPublicSessionView,
)
async def authenticate_shopify_public_session(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyPublicSessionView:
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

    try:
        invitation = await ShopifyInvitationService().require_activatable(
            session,
            shop_domain=shopify_session.shop_domain,
        )
    except ShopifyInvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

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
