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
    PublicCatalogSourceCreateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["public catalog ingestion"])


@router.post(
    "/workspaces/{workspace_id}/public-catalog-sources",
    response_model=CatalogSourceView,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_catalog_source(
    workspace_id: uuid.UUID,
    payload: PublicCatalogSourceCreateRequest,
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
        raise AuthorizationError(
            "Catalog source management permission required"
        )

    source = CatalogSource(
        workspace_id=workspace_id,
        name=payload.name,
        source_type=payload.source_type,
        status="draft",
        config={
            "start_url": payload.start_url,
            "product_urls": payload.product_urls,
            "authorized_domain_confirmed": (
                payload.authorized_domain_confirmed
            ),
            "max_products": payload.max_products,
            "max_sitemaps": payload.max_sitemaps,
            "crawl_delay_seconds": payload.crawl_delay_seconds,
        },
    )
    session.add(source)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.public_source_created",
            entity_type="catalog_source",
            entity_id=source.id,
            payload={
                "source_type": source.source_type,
                "name": source.name,
                "host": _source_host(payload),
                "max_products": payload.max_products,
            },
        )
    )
    await session.commit()
    await session.refresh(source)
    return CatalogSourceView.model_validate(source)


def _source_host(payload: PublicCatalogSourceCreateRequest) -> str:
    from urllib.parse import urlparse

    seed = payload.start_url or payload.product_urls[0]
    return urlparse(seed).hostname or ""
