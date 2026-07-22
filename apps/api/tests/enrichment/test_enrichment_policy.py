from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from catora_api.api.enrichment_policy import (
    _require_policy_management,
    get_enrichment_policy,
    set_enrichment_policy,
)
from catora_api.auth.service import AuthContext, AuthorizationError, AuthService
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import WorkspaceEnrichmentPolicy
from catora_api.enrichment.policies import (
    WorkspaceEnrichmentPolicyService,
    merge_brand_controls,
)
from catora_api.enrichment.types import BrandControls
from catora_api.main import app
from catora_api.schemas.enrichment_policy import WorkspaceEnrichmentPolicyUpdate


class PolicySession:
    def __init__(self, policy: WorkspaceEnrichmentPolicy | None) -> None:
        self.policy = policy
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    async def scalar(self, _statement: object) -> WorkspaceEnrichmentPolicy | None:
        return self.policy

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, WorkspaceEnrichmentPolicy):
            self.policy = value

    async def flush(self) -> None:
        self.flush_count += 1
        if self.policy is not None and self.policy.id is None:
            self.policy.id = uuid.uuid4()
            now = datetime.now(UTC)
            self.policy.created_at = now
            self.policy.updated_at = now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _value: object) -> None:
        return None


class FakeAuthService:
    def __init__(self, role: str) -> None:
        self.role = role

    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> object:
        return SimpleNamespace(role=self.role)


def _context() -> object:
    return SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4()))


def _policy(workspace_id: uuid.UUID) -> WorkspaceEnrichmentPolicy:
    now = datetime.now(UTC)
    return WorkspaceEnrichmentPolicy(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        brand_controls=BrandControls(
            tone="formal and factual",
            banned_claims=("best",),
            required_terms=("solid oak",),
            locked_fields=("warranty_months",),
            maximum_lengths={"title": 80, "description": 200},
        ).model_dump(mode="json"),
        max_run_budget_microunits=5_000,
        created_at=now,
        updated_at=now,
    )


def test_request_controls_can_only_tighten_workspace_policy() -> None:
    workspace = BrandControls(
        tone="formal and factual",
        banned_claims=("best",),
        required_terms=("solid oak",),
        locked_fields=("warranty_months",),
        maximum_lengths={"title": 80, "description": 200},
    )
    requested = BrandControls(
        tone="casual",
        banned_claims=("cheapest",),
        required_terms=("responsibly sourced",),
        locked_fields=("materials",),
        maximum_lengths={"title": 120, "description": 100, "faq": 500},
    )

    merged = merge_brand_controls(workspace, requested)

    assert merged.tone == "formal and factual"
    assert merged.banned_claims == ("best", "cheapest")
    assert merged.required_terms == ("solid oak", "responsibly sourced")
    assert merged.locked_fields == ("warranty_months", "materials")
    assert merged.maximum_lengths == {
        "title": 80,
        "description": 100,
        "faq": 500,
    }


@pytest.mark.asyncio
async def test_resolve_applies_workspace_budget_and_controls() -> None:
    workspace_id = uuid.uuid4()
    policy = _policy(workspace_id)
    service = WorkspaceEnrichmentPolicyService()

    effective = await service.resolve(
        cast(Any, PolicySession(policy)),
        workspace_id=workspace_id,
        requested_controls=BrandControls(
            locked_fields=("materials",),
            maximum_lengths={"title": 120},
        ),
        system_max_run_budget_microunits=10_000,
    )

    assert effective.max_run_budget_microunits == 5_000
    assert effective.brand_controls.tone == "formal and factual"
    assert effective.brand_controls.locked_fields == (
        "warranty_months",
        "materials",
    )
    assert effective.brand_controls.maximum_lengths["title"] == 80


@pytest.mark.asyncio
async def test_resolve_without_policy_preserves_request_controls() -> None:
    requested = BrandControls(tone="concise", locked_fields=("materials",))

    effective = await WorkspaceEnrichmentPolicyService().resolve(
        cast(Any, PolicySession(None)),
        workspace_id=uuid.uuid4(),
        requested_controls=requested,
        system_max_run_budget_microunits=10_000,
    )

    assert effective.brand_controls == requested
    assert effective.max_run_budget_microunits == 10_000


@pytest.mark.asyncio
async def test_policy_api_creates_record_and_audit_event() -> None:
    workspace_id = uuid.uuid4()
    session = PolicySession(None)
    payload = WorkspaceEnrichmentPolicyUpdate(
        brand_controls=BrandControls(
            tone="formal",
            locked_fields=("materials",),
        ),
        max_run_budget_microunits=2_500,
    )

    response = await set_enrichment_policy(
        workspace_id,
        payload,
        cast(Any, session),
        cast(AuthService, FakeAuthService("admin")),
        cast(AuthContext, _context()),
    )

    assert response.workspace_id == workspace_id
    assert response.brand_controls.tone == "formal"
    assert response.max_run_budget_microunits == 2_500
    assert session.commit_count == 1
    events = [item for item in session.added if isinstance(item, AuditEvent)]
    assert [event.event_type for event in events] == ["enrichment.policy_updated"]


@pytest.mark.asyncio
async def test_policy_get_is_tenant_scoped() -> None:
    workspace_id = uuid.uuid4()
    policy = _policy(workspace_id)

    response = await get_enrichment_policy(
        workspace_id,
        cast(Any, PolicySession(policy)),
        cast(AuthService, FakeAuthService("viewer")),
        cast(AuthContext, _context()),
    )

    assert response.id == policy.id
    assert response.workspace_id == workspace_id


def test_policy_management_is_owner_admin_only() -> None:
    _require_policy_management("owner")
    _require_policy_management("admin")
    with pytest.raises(AuthorizationError, match="policy management"):
        _require_policy_management("analyst")


def test_policy_api_contracts_are_registered() -> None:
    path = "/api/v1/workspaces/{workspace_id}/enrichment-policy"
    operations = app.openapi()["paths"][path]

    assert operations["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/WorkspaceEnrichmentPolicyView")
    assert operations["put"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/WorkspaceEnrichmentPolicyView")


def test_policy_model_has_one_record_per_workspace() -> None:
    constraints = WorkspaceEnrichmentPolicy.__table__.constraints
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("workspace_id",) in unique_columns
