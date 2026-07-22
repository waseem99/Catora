from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from catora_api.db.models.intents import BuyerIntent, IntentProductMatch
from catora_api.intents.execution import (
    IntentRunDataError,
    IntentRunService,
    build_candidates,
    source_snapshot_hash,
)
from catora_api.intents.types import IntentConstraint, StructuredBuyerIntent
from catora_api.schemas.intent_runs import IntentRunCreateRequest


class ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class RunSession:
    def __init__(self, *, intent: BuyerIntent, scalar_batches: list[list[object]]) -> None:
        self.intent = intent
        self.scalar_batches = list(scalar_batches)
        self.added: list[object] = []
        self.flush_count = 0

    async def scalar(self, _statement: object) -> BuyerIntent:
        return self.intent

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList(self.scalar_batches.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        now = datetime.now(UTC)
        for value in self.added:
            if getattr(value, "created_at", None) is None:
                value.created_at = now
            if getattr(value, "updated_at", None) is None:
                value.updated_at = now


def _intent(workspace_id: uuid.UUID, lineage_id: uuid.UUID) -> BuyerIntent:
    structured = StructuredBuyerIntent(
        query="A compact sofa no wider than 210 cm",
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
    now = datetime.now(UTC)
    return BuyerIntent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        supersedes_id=None,
        name="Compact sofa",
        query=structured.query,
        structured_intent=structured.model_dump(mode="json"),
        source="user_entered",
        version=2,
        approval_status="approved",
        created_at=now,
        updated_at=now,
    )


def _category(workspace_id: uuid.UUID, key: str = "sofas") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id, key=key)


def _product(
    workspace_id: uuid.UUID,
    *,
    category_id: uuid.UUID | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        primary_category_id=category_id,
        status="active",
        deleted_at=None,
    )


def _variant(workspace_id: uuid.UUID, product_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        deleted_at=None,
    )


def _attribute(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    value: object,
    variant_id: uuid.UUID | None = None,
    key: str = "width",
    value_state: str = "present",
    unit: str | None = "mm",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        variant_id=variant_id,
        key=key,
        value=value,
        value_state=value_state,
        unit=unit,
    )


def _evidence(workspace_id: uuid.UUID, attribute_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        attribute_id=attribute_id,
        source_record_id=uuid.uuid4(),
        field_path="product.dimensions.width",
        excerpt="Width: 2000 mm",
        checksum="a" * 64,
    )


@pytest.mark.asyncio
async def test_execute_persists_reconciled_product_and_variant_results() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    intent = _intent(workspace_id, lineage_id)
    category = _category(workspace_id)
    first = _product(workspace_id, category_id=category.id)
    second = _product(workspace_id, category_id=category.id)
    third = _product(workspace_id, category_id=category.id)
    second_variant = _variant(workspace_id, second.id)
    first_width = _attribute(workspace_id, first.id, value=2000)
    second_width = _attribute(
        workspace_id,
        second.id,
        value=2200,
        variant_id=second_variant.id,
    )
    session = RunSession(
        intent=intent,
        scalar_batches=[
            [first, second, third],
            [category],
            [second_variant],
            [first_width, second_width],
            [_evidence(workspace_id, first_width.id), _evidence(workspace_id, second_width.id)],
        ],
    )

    persisted = await IntentRunService().execute(
        cast(Any, session),
        workspace_id=workspace_id,
        lineage_id=lineage_id,
        intent_version=2,
    )

    assert persisted.run.status == "completed"
    assert len(persisted.run.source_snapshot_hash) == 64
    assert persisted.summary.target_count == 3
    assert persisted.summary.product_count == 3
    assert persisted.summary.confident_match_count == 1
    assert persisted.summary.non_match_count == 1
    assert persisted.summary.possible_match_missing_data_count == 1
    statuses = {match.product_id: match.status for match in persisted.matches}
    assert statuses == {
        first.id: "confident_match",
        second.id: "non_match",
        third.id: "possible_match_missing_data",
    }
    confident = next(match for match in persisted.matches if match.product_id == first.id)
    assert confident.explanation["hard_constraints"][0]["evidence"]
    assert session.flush_count == 2
    assert sum(isinstance(item, IntentProductMatch) for item in session.added) == 3


def test_variant_facts_override_product_facts_and_keep_evidence() -> None:
    workspace_id = uuid.uuid4()
    category = _category(workspace_id)
    product = _product(workspace_id, category_id=category.id)
    variant = _variant(workspace_id, product.id)
    product_width = _attribute(workspace_id, product.id, value=2000)
    variant_width = _attribute(
        workspace_id,
        product.id,
        value=2050,
        variant_id=variant.id,
    )
    evidence = _evidence(workspace_id, variant_width.id)

    candidates = build_candidates(
        cast(Any, (product,)),
        cast(Any, (category,)),
        cast(Any, (variant,)),
        cast(Any, (product_width, variant_width)),
        cast(Any, (evidence,)),
    )

    assert len(candidates) == 1
    assert candidates[0].variant_id == variant.id
    assert candidates[0].category_key == "sofas"
    assert candidates[0].facts[0].value == 2050
    assert candidates[0].facts[0].evidence[0].source_record_id == evidence.source_record_id
    assert candidates[0].facts[0].evidence[0].excerpt == evidence.excerpt


def test_non_present_attributes_drop_stale_values() -> None:
    workspace_id = uuid.uuid4()
    category = _category(workspace_id)
    product = _product(workspace_id, category_id=category.id)
    stale = _attribute(
        workspace_id,
        product.id,
        value=2000,
        value_state="missing",
    )

    candidate = build_candidates(
        cast(Any, (product,)),
        cast(Any, (category,)),
        (),
        cast(Any, (stale,)),
        (),
    )[0]

    assert candidate.facts[0].value_state == "missing"
    assert candidate.facts[0].value is None


def test_duplicate_canonical_attributes_fail_closed() -> None:
    workspace_id = uuid.uuid4()
    category = _category(workspace_id)
    product = _product(workspace_id, category_id=category.id)
    first = _attribute(workspace_id, product.id, value=2000)
    duplicate = _attribute(workspace_id, product.id, value=2100)

    with pytest.raises(IntentRunDataError, match="Multiple canonical attributes"):
        build_candidates(
            cast(Any, (product,)),
            cast(Any, (category,)),
            (),
            cast(Any, (first, duplicate)),
            (),
        )


def test_source_snapshot_hash_is_deterministic_and_value_sensitive() -> None:
    workspace_id = uuid.uuid4()
    lineage_id = uuid.uuid4()
    intent = _intent(workspace_id, lineage_id)
    structured = StructuredBuyerIntent.model_validate(intent.structured_intent)
    category = _category(workspace_id)
    product = _product(workspace_id, category_id=category.id)
    first = _attribute(workspace_id, product.id, value=2000)
    second = _attribute(workspace_id, product.id, value=2050)
    first_candidates = build_candidates(
        cast(Any, (product,)), cast(Any, (category,)), (), cast(Any, (first,)), ()
    )
    same_candidates = build_candidates(
        cast(Any, (product,)), cast(Any, (category,)), (), cast(Any, (first,)), ()
    )
    changed_candidates = build_candidates(
        cast(Any, (product,)), cast(Any, (category,)), (), cast(Any, (second,)), ()
    )

    assert source_snapshot_hash(intent, structured, first_candidates) == source_snapshot_hash(
        intent,
        structured,
        same_candidates,
    )
    assert source_snapshot_hash(intent, structured, first_candidates) != source_snapshot_hash(
        intent,
        structured,
        changed_candidates,
    )


def test_product_query_requires_active_non_deleted_products() -> None:
    from sqlalchemy import select

    from catora_api.db.models.catalog import Product

    statement = select(Product).where(
        Product.workspace_id == uuid.uuid4(),
        Product.status == "active",
        Product.deleted_at.is_(None),
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "products.status" in sql
    assert "products.deleted_at IS NULL" in sql


def test_run_request_rejects_duplicate_product_ids() -> None:
    product_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="product_ids must be unique"):
        IntentRunCreateRequest(
            intent_version=1,
            product_ids=(product_id, product_id),
        )


def test_intent_run_openapi_contracts_are_registered() -> None:
    from catora_api.main import app

    create_path = "/api/v1/workspaces/{workspace_id}/buyer-intents/{lineage_id}/runs"
    detail_path = "/api/v1/workspaces/{workspace_id}/intent-runs/{run_id}"
    matches_path = detail_path + "/matches"
    paths = app.openapi()["paths"]

    assert paths[create_path]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentRunView")
    assert paths[detail_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentRunView")
    assert paths[matches_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentProductMatchListResponse")


def test_candidate_assembly_is_deterministic_for_10000_products() -> None:
    workspace_id = uuid.UUID("00000000-0000-0000-0000-000000000100")
    lineage_id = uuid.UUID("00000000-0000-0000-0000-000000000200")
    category = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000300"),
        workspace_id=workspace_id,
        key="sofas",
    )
    products = tuple(
        SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"catora:intent-product:{index}"),
            workspace_id=workspace_id,
            primary_category_id=category.id,
            status="active",
            deleted_at=None,
        )
        for index in range(10_000)
    )
    attributes = tuple(
        SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"catora:intent-width:{index}"),
            workspace_id=workspace_id,
            product_id=product.id,
            variant_id=None,
            key="width",
            value=1800 + index % 500,
            value_state="present",
            unit="mm",
        )
        for index, product in enumerate(products)
    )
    intent = _intent(workspace_id, lineage_id)
    structured = StructuredBuyerIntent.model_validate(intent.structured_intent)

    first = build_candidates(
        cast(Any, products),
        cast(Any, (category,)),
        (),
        cast(Any, attributes),
        (),
    )
    second = build_candidates(
        cast(Any, tuple(reversed(products))),
        cast(Any, (category,)),
        (),
        cast(Any, tuple(reversed(attributes))),
        (),
    )

    assert len(first) == 10_000
    assert first == second
    assert source_snapshot_hash(intent, structured, first) == source_snapshot_hash(
        intent,
        structured,
        second,
    )
