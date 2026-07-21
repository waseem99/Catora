from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from catora_api.auth.dependencies import (
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent
from catora_api.db.models.catalog import CatalogSource
from catora_api.schemas.ingestion import (
    CatalogSourceView,
    ShopifySourceCreateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["shopify catalog ingestion"])


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
    if not can(Role(membership.role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")

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
