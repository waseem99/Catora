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
from catora_api.db.models.reporting import AuditEvent
from catora_api.enrichment.policies import WorkspaceEnrichmentPolicyService
from catora_api.schemas.enrichment_policy import (
    WorkspaceEnrichmentPolicyUpdate,
    WorkspaceEnrichmentPolicyView,
)

router = APIRouter(prefix="/api/v1", tags=["enrichment policy"])
policy_service = WorkspaceEnrichmentPolicyService()


def _require_policy_management(role: str) -> None:
    if not can(Role(role), "members.manage"):
        raise AuthorizationError("Workspace enrichment policy management permission required")


@router.get(
    "/workspaces/{workspace_id}/enrichment-policy",
    response_model=WorkspaceEnrichmentPolicyView,
)
async def get_enrichment_policy(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> WorkspaceEnrichmentPolicyView:
    await auth_service.membership(session, context.user.id, workspace_id)
    policy = await policy_service.get(session, workspace_id=workspace_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Workspace enrichment policy not found")
    return WorkspaceEnrichmentPolicyView.model_validate(policy)


@router.put(
    "/workspaces/{workspace_id}/enrichment-policy",
    response_model=WorkspaceEnrichmentPolicyView,
)
async def set_enrichment_policy(
    workspace_id: uuid.UUID,
    payload: WorkspaceEnrichmentPolicyUpdate,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> WorkspaceEnrichmentPolicyView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_policy_management(membership.role)
    policy = await policy_service.set(
        session,
        workspace_id=workspace_id,
        brand_controls=payload.brand_controls,
        max_run_budget_microunits=payload.max_run_budget_microunits,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="enrichment.policy_updated",
            entity_type="workspace_enrichment_policy",
            entity_id=policy.id,
            payload={
                "max_run_budget_microunits": policy.max_run_budget_microunits,
                "locked_field_count": len(payload.brand_controls.locked_fields),
                "banned_claim_count": len(payload.brand_controls.banned_claims),
                "required_term_count": len(payload.brand_controls.required_terms),
            },
        )
    )
    await session.commit()
    await session.refresh(policy)
    return WorkspaceEnrichmentPolicyView.model_validate(policy)
