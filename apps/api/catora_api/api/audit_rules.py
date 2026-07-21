from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from catora_api.auditing.custom_rules import (
    CustomAuditRuleConflictError,
    CustomAuditRuleRecord,
    CustomAuditRuleReferenceError,
    CustomAuditRuleService,
)
from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent
from catora_api.schemas.audit_rules import (
    CustomAuditRuleCreateRequest,
    CustomAuditRuleView,
)

router = APIRouter(prefix="/api/v1", tags=["audit rules"])
custom_rule_service = CustomAuditRuleService()


@router.get(
    "/workspaces/{workspace_id}/audit-rules",
    response_model=list[CustomAuditRuleView],
)
async def list_custom_audit_rules(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[CustomAuditRuleView]:
    await auth_service.membership(session, context.user.id, workspace_id)
    records = await custom_rule_service.list(session, workspace_id=workspace_id)
    return [_view(record) for record in records]


@router.post(
    "/workspaces/{workspace_id}/audit-rules",
    response_model=CustomAuditRuleView,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_audit_rule(
    workspace_id: uuid.UUID,
    payload: CustomAuditRuleCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> CustomAuditRuleView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "catalog.taxonomy.manage"):
        raise AuthorizationError("Custom audit rule management requires owner or admin access")

    try:
        record = await custom_rule_service.create(
            session,
            workspace_id=workspace_id,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            taxonomy_version=payload.taxonomy_version,
            category_key=payload.category_key,
            field_key=payload.field_key,
            relationship=payload.relationship,
            related_field_key=payload.related_field_key,
            severity=payload.severity,
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=context.user.id,
                event_type="audit.custom_rule_created",
                entity_type="rule_version",
                entity_id=record.version.id,
                payload={
                    "rule_key": record.definition.key,
                    "taxonomy_version": record.version.version,
                    "category_key": record.rule.category_key,
                    "field_key": record.rule.field_key,
                    "relationship": record.relationship,
                    "related_field_key": record.related_field_key,
                    "severity": record.rule.severity,
                },
            )
        )
        await session.commit()
    except CustomAuditRuleConflictError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CustomAuditRuleReferenceError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A custom audit rule with this key and version already exists",
        ) from exc
    return _view(record)


def _view(record: CustomAuditRuleRecord) -> CustomAuditRuleView:
    return CustomAuditRuleView(
        rule_definition_id=record.definition.id,
        rule_version_id=record.version.id,
        workspace_id=cast(uuid.UUID, record.definition.workspace_id),
        key=record.definition.key,
        name=record.definition.name,
        description=record.definition.description,
        taxonomy_version=record.version.version,
        category_key=record.rule.category_key,
        field_key=record.rule.field_key,
        relationship=record.relationship,
        related_field_key=record.related_field_key,
        severity=record.rule.severity,
        is_immutable=record.version.is_immutable,
    )
