from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from catora_api.db.models.intents import BuyerIntent
from catora_api.intents.service import (
    BuyerIntentService,
    BuyerIntentVersionConflictError,
)
from catora_api.intents.types import IntentConstraint, StructuredBuyerIntent
from catora_api.schemas.intents import BuyerIntentCreateRequest, BuyerIntentView


class ScalarList:
    def __init__(self, values: list[BuyerIntent]) -> None:
        self._values = values

    def all(self) -> list[BuyerIntent]:
        return self._values


class IntentSession:
    def __init__(
        self,
        *,
        scalar_values: list[BuyerIntent | int | None] | None = None,
        scalars_values: list[list[BuyerIntent]] | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.scalars_values = list(scalars_values or [])
        self.added: list[object] = []
        self.flush_count = 0

    async def scalar(self, _statement: object) -> BuyerIntent | int | None:
        return self.scalar_values.pop(0)

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList(self.scalars_values.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


def _structured(query: str = "A compact sofa no wider than 210 cm") -> StructuredBuyerIntent:
    return StructuredBuyerIntent(
        query=query,
        category_keys=("sofas",),
        hard_constraints=(
            IntentConstraint(
                field_key="width",
                operator="less_than_or_equal",
                expected=210,
                unit="cm",
            ),
        ),
    )


def _stored(
    *,
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    version: int,
    approval_status: str = "draft",
) -> BuyerIntent:
    now = datetime.now(UTC)
    return BuyerIntent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        supersedes_id=None,
        name=f"Compact sofa v{version}",
        query=_structured().query,
        structured_intent=_structured().model_dump(mode="json"),
        source="user_entered",
        version=version,
        approval_status=approval_status,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_starts_a_new_draft_lineage() -> None:
    workspace_id = uuid.uuid4()
    session = IntentSession()

    intent = await BuyerIntentService().create(
        cast(Any, session),
        workspace_id=workspace_id,
        name="Compact sofa",
        source="user_entered",
        structured_intent=_structured(),
    )

    assert intent.workspace_id == workspace_id
    assert intent.version == 1
    assert intent.approval_status == "draft"
    assert intent.supersedes_id is None
    assert intent.query == _structured().query
    assert session.added == [intent]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_revision_appends_a_version_without_mutating_previous_content() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    current = _stored(workspace_id=workspace_id, lineage_id=lineage_id, version=2)
    original_name = current.name
    session = IntentSession(scalar_values=[current])

    revised = await BuyerIntentService().revise(
        cast(Any, session),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        expected_version=2,
        name="Revised compact sofa",
        structured_intent=_structured("A revised compact sofa query"),
    )

    assert current.name == original_name
    assert current.version == 2
    assert current.approval_status == "superseded"
    assert revised.lineage_id == lineage_id
    assert revised.supersedes_id == current.id
    assert revised.version == 3
    assert revised.approval_status == "draft"
    assert revised.query == "A revised compact sofa query"
    assert session.added == [revised]


@pytest.mark.asyncio
async def test_revision_rejects_a_stale_expected_version() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    current = _stored(workspace_id=workspace_id, lineage_id=lineage_id, version=4)
    session = IntentSession(scalar_values=[current])

    with pytest.raises(BuyerIntentVersionConflictError, match="expected 3, found 4"):
        await BuyerIntentService().revise(
            cast(Any, session),
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            expected_version=3,
            name="Stale edit",
            structured_intent=_structured(),
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_approval_supersedes_the_prior_approved_version() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    current = _stored(workspace_id=workspace_id, lineage_id=lineage_id, version=3)
    previous = _stored(
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        version=2,
        approval_status="approved",
    )
    session = IntentSession(scalar_values=[current], scalars_values=[[previous]])

    approved = await BuyerIntentService().approve(
        cast(Any, session),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        expected_version=3,
    )

    assert approved is current
    assert current.approval_status == "approved"
    assert previous.approval_status == "superseded"
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_latest_list_uses_reconciled_total_and_stable_page() -> None:
    workspace_id = uuid.uuid4()
    first = _stored(workspace_id=workspace_id, lineage_id=uuid.uuid4(), version=2)
    second = _stored(workspace_id=workspace_id, lineage_id=uuid.uuid4(), version=1)
    session = IntentSession(scalar_values=[2], scalars_values=[[first, second]])

    page = await BuyerIntentService().list_latest(
        cast(Any, session),
        workspace_id=workspace_id,
        approval_status=None,
        source=None,
        offset=0,
        limit=100,
    )

    assert page.total == 2
    assert page.items == (first, second)


@pytest.mark.asyncio
async def test_version_history_is_paginated_with_an_exact_total() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    latest = _stored(workspace_id=workspace_id, lineage_id=lineage_id, version=2)
    first = _stored(workspace_id=workspace_id, lineage_id=lineage_id, version=1)
    session = IntentSession(scalar_values=[2], scalars_values=[[latest, first]])

    page = await BuyerIntentService().versions(
        cast(Any, session),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        offset=0,
        limit=100,
    )

    assert page.total == 2
    assert page.items == (latest, first)


def test_model_constraints_protect_lineage_versions_and_statuses() -> None:
    names = {constraint.name for constraint in BuyerIntent.__table__.constraints}
    assert "ck_buyer_intents_valid_approval_status" in names
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in BuyerIntent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("workspace_id", "lineage_id", "version") in unique_columns


def test_schema_round_trip_preserves_structured_intent() -> None:
    payload = BuyerIntentCreateRequest(
        name="  Compact   sofa  ",
        source="user_entered",
        structured_intent=_structured(),
    )
    now = datetime.now(UTC)
    view = BuyerIntentView.model_validate(
        {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "lineage_id": uuid.uuid4(),
            "supersedes_id": None,
            "name": payload.name,
            "query": payload.structured_intent.query,
            "structured_intent": payload.structured_intent.model_dump(mode="json"),
            "source": payload.source,
            "version": 1,
            "approval_status": "draft",
            "created_at": now,
            "updated_at": now,
        }
    )

    assert payload.name == "Compact sofa"
    assert view.structured_intent == payload.structured_intent
    with pytest.raises(ValidationError):
        BuyerIntentCreateRequest.model_validate(
            {
                "name": "Intent",
                "source": "unknown",
                "structured_intent": _structured().model_dump(mode="json"),
            }
        )


def test_openapi_registers_versioned_intent_contracts() -> None:
    from catora_api.main import app

    collection = "/api/v1/workspaces/{workspace_id}/buyer-intents"
    detail = collection + "/{lineage_id}"
    paths = app.openapi()["paths"]

    assert paths[collection]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/BuyerIntentView")
    assert paths[detail]["put"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/BuyerIntentView")
    assert detail + "/versions" in paths
    assert detail + "/approve" in paths
