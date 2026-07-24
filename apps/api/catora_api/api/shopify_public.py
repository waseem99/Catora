from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.schemas.shopify_public import (
    ShopifyStoreInvitationCreateRequest,
    ShopifyStoreInvitationView,
)
from catora_api.shopify.invitations import (
    ShopifyInvitationError,
    ShopifyInvitationService,
)

router = APIRouter(tags=["shopify public app invitations"])


def _require_source_management(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


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
