from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent
from catora_api.schemas.taxonomy import (
    AssignProductCategoriesRequest,
    CategoryPreviewResponse,
    CategorySummary,
    ProductCategoryAssignmentResponse,
    TaxonomyCompileResponse,
)
from catora_api.taxonomy import taxonomy_fingerprint
from catora_api.taxonomy.assignment import (
    CATEGORY_CLASSIFIER_VERSION,
    ProductCategoryAssignment,
    TaxonomyAssignmentConflictError,
    TaxonomyAssignmentService,
    TaxonomyCategoryNotFoundError,
    TaxonomyProductNotFoundError,
)

router = APIRouter(prefix="/api/v1", tags=["taxonomy"])
assignment_service = TaxonomyAssignmentService()


@router.post(
    "/workspaces/{workspace_id}/taxonomy/compile",
    response_model=TaxonomyCompileResponse,
)
async def compile_taxonomy(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> TaxonomyCompileResponse:
    await _require_taxonomy_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    summary = await assignment_service.compile_workspace(
        session,
        workspace_id=workspace_id,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="taxonomy.compiled",
            entity_type="workspace",
            entity_id=workspace_id,
            payload={
                "taxonomy_version": assignment_service.package.version,
                "taxonomy_fingerprint": summary.fingerprint,
                "categories_created": summary.categories_created,
                "fields_created": summary.fields_created,
                "rule_definitions_created": summary.rule_definitions_created,
                "rule_versions_created": summary.rule_versions_created,
            },
        )
    )
    await session.commit()
    return TaxonomyCompileResponse(
        categories_created=summary.categories_created,
        fields_created=summary.fields_created,
        rule_definitions_created=summary.rule_definitions_created,
        rule_versions_created=summary.rule_versions_created,
        taxonomy_version=assignment_service.package.version,
        fingerprint=summary.fingerprint,
    )


@router.get(
    "/workspaces/{workspace_id}/products/{product_id}/category-preview",
    response_model=CategoryPreviewResponse,
)
async def preview_product_category(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> CategoryPreviewResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        product, result = await assignment_service.preview_product(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
    except TaxonomyProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    package = assignment_service.package
    return CategoryPreviewResponse(
        product_id=product.id,
        taxonomy_version=package.version,
        taxonomy_fingerprint=taxonomy_fingerprint(package),
        classifier_version=CATEGORY_CLASSIFIER_VERSION,
        status=result.status,
        primary_category_key=result.primary_category_key,
        candidate_keys=list(result.candidate_keys),
        secondary_tag_keys=list(result.secondary_tag_keys),
        scores=result.scores,
    )


@router.get(
    "/workspaces/{workspace_id}/products/{product_id}/category-assignment",
    response_model=ProductCategoryAssignmentResponse,
)
async def get_product_category_assignment(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ProductCategoryAssignmentResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        assignment = await assignment_service.assignment(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
    except (TaxonomyProductNotFoundError, TaxonomyCategoryNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _assignment_response(assignment)


@router.put(
    "/workspaces/{workspace_id}/products/{product_id}/category-assignment",
    response_model=ProductCategoryAssignmentResponse,
)
async def assign_product_categories(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: AssignProductCategoriesRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ProductCategoryAssignmentResponse:
    await _require_taxonomy_manager(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        assignment = await assignment_service.assign(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
            taxonomy_version=payload.taxonomy_version,
            primary_category_key=payload.primary_category_key,
            secondary_category_keys=payload.secondary_category_keys,
            actor_user_id=context.user.id,
            reason=payload.reason,
        )
    except (TaxonomyProductNotFoundError, TaxonomyCategoryNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaxonomyAssignmentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.product_categories_assigned",
            entity_type="product",
            entity_id=product_id,
            payload={
                "taxonomy_version": payload.taxonomy_version,
                "primary_category_key": payload.primary_category_key,
                "secondary_category_keys": payload.secondary_category_keys,
                "assignment_source": "manual",
                "reason": payload.reason,
            },
        )
    )
    await session.commit()
    return _assignment_response(assignment)


async def _require_taxonomy_manager(
    *,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    workspace_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "catalog.taxonomy.manage"):
        raise AuthorizationError("Taxonomy management requires owner or admin access")


def _assignment_response(
    assignment: ProductCategoryAssignment,
) -> ProductCategoryAssignmentResponse:
    primary = assignment.primary_category
    return ProductCategoryAssignmentResponse(
        product_id=assignment.product.id,
        taxonomy_version=primary.taxonomy_version,
        primary_category=CategorySummary.model_validate(primary),
        secondary_categories=[
            CategorySummary.model_validate(category)
            for category in assignment.secondary_categories
        ],
    )
