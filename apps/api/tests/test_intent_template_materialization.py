from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import catora_api.api.intent_templates as intent_templates_api
from catora_api.db.models.intents import BuyerIntent
from catora_api.db.models.reporting import AuditEvent
from catora_api.schemas.intent_templates import BuyerIntentTemplateMaterializeRequest


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.refreshed: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


class FakeAuthService:
    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> SimpleNamespace:
        return SimpleNamespace(role="analyst")


class FakeIntentService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, _session: object, **kwargs: Any) -> BuyerIntent:
        self.calls.append(kwargs)
        structured = kwargs["structured_intent"]
        now = datetime.now(UTC)
        return BuyerIntent(
            id=uuid.uuid4(),
            workspace_id=kwargs["workspace_id"],
            lineage_id=uuid.uuid4(),
            supersedes_id=None,
            name=kwargs["name"],
            query=structured.query,
            structured_intent=structured.model_dump(mode="json"),
            source=kwargs["source"],
            version=1,
            approval_status="draft",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.asyncio
async def test_materialize_template_creates_audited_editable_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = FakeSession()
    service = FakeIntentService()
    monkeypatch.setattr(intent_templates_api, "intent_service", service)

    result = await intent_templates_api.materialize_template(
        workspace_id=workspace_id,
        template_key=" compact_space_sofa ",
        payload=BuyerIntentTemplateMaterializeRequest(
            expected_template_version=1,
            name="  Small living room sofa  ",
        ),
        session=session,
        auth_service=FakeAuthService(),
        context=SimpleNamespace(user=SimpleNamespace(id=user_id)),
    )

    assert result.template_key == "compact_space_sofa"
    assert result.template_version == 1
    assert result.taxonomy_version == "1.0.0"
    assert result.buyer_intent.name == "Small living room sofa"
    assert result.buyer_intent.source == "template"
    assert result.buyer_intent.version == 1
    assert result.buyer_intent.approval_status == "draft"
    assert service.calls[0]["source"] == "template"
    assert service.calls[0]["workspace_id"] == workspace_id
    assert session.commit_count == 1
    assert session.refreshed == [result.buyer_intent]

    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "intent.created_from_template"
    assert audit.actor_user_id == user_id
    assert audit.payload["template_key"] == "compact_space_sofa"
    assert audit.payload["template_version"] == 1
    assert audit.payload["taxonomy_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_materialize_template_rejects_stale_template_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeIntentService()
    monkeypatch.setattr(intent_templates_api, "intent_service", service)

    with pytest.raises(HTTPException) as captured:
        await intent_templates_api.materialize_template(
            workspace_id=uuid.uuid4(),
            template_key="compact_space_sofa",
            payload=BuyerIntentTemplateMaterializeRequest(expected_template_version=2),
            session=FakeSession(),
            auth_service=FakeAuthService(),
            context=SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4())),
        )

    assert captured.value.status_code == 409
    assert service.calls == []


def test_template_materialization_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/buyer-intent-templates/"
        "{template_key}/materialize"
    )
    operation = app.openapi()["paths"][path]["post"]

    assert operation["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/BuyerIntentTemplateMaterializationView")
