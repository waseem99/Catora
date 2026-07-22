from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent
from catora_api.db.models.catalog import Product
from catora_api.db.models.catalog_identity import (
    CommercialProductIdentity,
    ProductIdentityCandidate,
    ProductIdentityMembership,
)
from catora_api.identity_resolution import (
    ALGORITHM_VERSION,
    CatalogIdentityConflictError,
    CatalogIdentityNotFoundError,
    CatalogIdentityService,
)
from catora_api.schemas.catalog_identity import (
    IdentityCandidateRefreshResponse,
    IdentityProductSummary,
    IdentitySignal,
    LinkProductsRequest,
    ProductIdentityCandidateListResponse,
    ProductIdentityCandidateView,
    ProductIdentityMemberView,
    ProductIdentityView,
    RejectIdentityCandidateRequest,
    UnlinkProductRequest,
    UnlinkProductResponse,
)

router = APIRouter(prefix="/api/v1", tags=["catalog identity"])
identity_service = CatalogIdentityService()
CandidateStatus = Literal["pending", "accepted", "rejected", "superseded"]
MatchType = Literal["deterministic", "fuzzy"]
IdentityStatus = Literal["active", "dissolved"]


@router.get(
    "/workspaces/{workspace_id}/identity-candidates",
    response_model=ProductIdentityCandidateListResponse,
)
async def list_identity_candidates(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    candidate_status: Annotated[CandidateStatus | None, Query(alias="status")] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductIdentityCandidateListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    filters = [ProductIdentityCandidate.workspace_id == workspace_id]
    if candidate_status is not None:
        filters.append(ProductIdentityCandidate.status == candidate_status)
    total = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(ProductIdentityCandidate)
                .where(*filters)
            )
        )
        or 0
    )

    left_product = aliased(Product)
    right_product = aliased(Product)
    rows = (
        await session.execute(
            select(ProductIdentityCandidate, left_product, right_product)
            .join(left_product, left_product.id == ProductIdentityCandidate.left_product_id)
            .join(right_product, right_product.id == ProductIdentityCandidate.right_product_id)
            .where(
                *filters,
                left_product.workspace_id == workspace_id,
                right_product.workspace_id == workspace_id,
            )
            .order_by(
                ProductIdentityCandidate.score_basis_points.desc(),
                ProductIdentityCandidate.created_at,
                ProductIdentityCandidate.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ProductIdentityCandidateListResponse(
        items=[
            _candidate_view(
                cast(ProductIdentityCandidate, row[0]),
                cast(Product, row[1]),
                cast(Product, row[2]),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/workspaces/{workspace_id}/identity-candidates/refresh",
    response_model=IdentityCandidateRefreshResponse,
)
async def refresh_identity_candidates(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    max_products: Annotated[int, Query(ge=2, le=5000)] = 1000,
) -> IdentityCandidateRefreshResponse:
    await _require_identity_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    summary = await identity_service.refresh_candidates(
        session,
        workspace_id=workspace_id,
        max_products=max_products,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.identity_candidates_refreshed",
            entity_type="workspace",
            entity_id=workspace_id,
            payload={
                "algorithm_version": ALGORITHM_VERSION,
                "products_considered": summary.products_considered,
                "candidates_created": summary.candidates_created,
                "candidates_updated": summary.candidates_updated,
                "candidates_superseded": summary.candidates_superseded,
                "truncated": summary.truncated,
            },
        )
    )
    await session.commit()
    return IdentityCandidateRefreshResponse(
        products_considered=summary.products_considered,
        candidates_created=summary.candidates_created,
        candidates_updated=summary.candidates_updated,
        candidates_superseded=summary.candidates_superseded,
        truncated=summary.truncated,
        algorithm_version=ALGORITHM_VERSION,
    )


@router.get(
    "/workspaces/{workspace_id}/products/{product_id}/identity",
    response_model=ProductIdentityView,
)
async def get_product_identity(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ProductIdentityView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        identity, members = await identity_service.active_identity_members(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
    except CatalogIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _identity_view(identity, members)


@router.post(
    "/workspaces/{workspace_id}/products/{product_id}/identity-link",
    response_model=ProductIdentityView,
)
async def link_product_identity(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: LinkProductsRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ProductIdentityView:
    await _require_identity_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        identity = await identity_service.link_products(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
            target_product_id=payload.target_product_id,
            actor_user_id=context.user.id,
            reason=payload.reason,
            candidate_id=payload.candidate_id,
        )
    except CatalogIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogIdentityConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.product_identity_linked",
            entity_type="commercial_product_identity",
            entity_id=identity.id,
            payload={
                "product_id": str(product_id),
                "target_product_id": str(payload.target_product_id),
                "candidate_id": str(payload.candidate_id) if payload.candidate_id else None,
                "reason": payload.reason,
            },
        )
    )
    await session.commit()
    _, members = await identity_service.active_identity_members(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
    )
    return _identity_view(identity, members)


@router.post(
    "/workspaces/{workspace_id}/products/{product_id}/identity-unlink",
    response_model=UnlinkProductResponse,
)
async def unlink_product_identity(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: UnlinkProductRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> UnlinkProductResponse:
    await _require_identity_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        identity_id, dissolved = await identity_service.unlink_product(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
            actor_user_id=context.user.id,
            reason=payload.reason,
        )
    except CatalogIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.product_identity_unlinked",
            entity_type="commercial_product_identity",
            entity_id=identity_id,
            payload={
                "product_id": str(product_id),
                "reason": payload.reason,
                "identity_dissolved": dissolved,
            },
        )
    )
    await session.commit()
    return UnlinkProductResponse(
        identity_id=identity_id,
        product_id=product_id,
        dissolved=dissolved,
    )


@router.post(
    "/workspaces/{workspace_id}/identity-candidates/{candidate_id}/reject",
    response_model=ProductIdentityCandidateView,
)
async def reject_identity_candidate(
    workspace_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: RejectIdentityCandidateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ProductIdentityCandidateView:
    await _require_identity_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        candidate = await identity_service.reject_candidate(
            session,
            workspace_id=workspace_id,
            candidate_id=candidate_id,
            actor_user_id=context.user.id,
            reason=payload.reason,
        )
    except CatalogIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogIdentityConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.identity_candidate_rejected",
            entity_type="product_identity_candidate",
            entity_id=candidate.id,
            payload={
                "left_product_id": str(candidate.left_product_id),
                "right_product_id": str(candidate.right_product_id),
                "reason": payload.reason,
            },
        )
    )
    await session.commit()
    products = await identity_service.products_by_ids(
        session,
        workspace_id=workspace_id,
        product_ids=(candidate.left_product_id, candidate.right_product_id),
    )
    return _candidate_view(
        candidate,
        products[candidate.left_product_id],
        products[candidate.right_product_id],
    )


async def _require_identity_manager(
    *,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    workspace_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(
        session,
        context.user.id,
        workspace_id,
    )
    if not can(Role(membership.role), "catalog.identity.manage"):
        raise AuthorizationError("Catalog identity management permission required")


def _candidate_view(
    candidate: ProductIdentityCandidate,
    left_product: Product,
    right_product: Product,
) -> ProductIdentityCandidateView:
    return ProductIdentityCandidateView(
        id=candidate.id,
        left_product=IdentityProductSummary.model_validate(left_product),
        right_product=IdentityProductSummary.model_validate(right_product),
        match_type=cast(MatchType, candidate.match_type),
        score_basis_points=candidate.score_basis_points,
        signals=[IdentitySignal.model_validate(signal) for signal in candidate.signals],
        algorithm_version=candidate.algorithm_version,
        status=cast(CandidateStatus, candidate.status),
        resolved_by_user_id=candidate.resolved_by_user_id,
        resolved_at=candidate.resolved_at,
        resolution_reason=candidate.resolution_reason,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _identity_view(
    identity: CommercialProductIdentity,
    members: list[tuple[ProductIdentityMembership, Product]],
) -> ProductIdentityView:
    return ProductIdentityView(
        identity_id=identity.id,
        status=cast(IdentityStatus, identity.status),
        members=[
            ProductIdentityMemberView(
                product=IdentityProductSummary.model_validate(product),
                linked_by_user_id=membership.linked_by_user_id,
                link_reason=membership.link_reason,
                linked_at=membership.created_at,
            )
            for membership, product in members
        ],
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )
