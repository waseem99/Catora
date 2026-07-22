from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from catora_api.db.models.intents import (
    BuyerIntent,
    IntentRun,
    IntentSuiteMember,
)
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    PersistedMatchSnapshot,
)
from catora_api.intents.intent_breakdown import build_intent_coverage
from catora_api.intents.types import (
    ConstraintEvaluation,
    IntentMatchResult,
    StructuredBuyerIntent,
)


def _intent(
    *,
    index: int,
    source: str,
    category_keys: tuple[str, ...],
) -> BuyerIntent:
    structured = StructuredBuyerIntent(
        query=f"Intent {index}",
        category_keys=category_keys,
    )
    now = datetime.now(UTC)
    return BuyerIntent(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-intent:{index}"),
        workspace_id=uuid.uuid4(),
        lineage_id=uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-lineage:{index}"),
        supersedes_id=None,
        name=f"Intent {index}",
        query=structured.query,
        structured_intent=structured.model_dump(mode="json"),
        source=source,
        version=2,
        approval_status="approved",
        created_at=now,
        updated_at=now,
    )


def _member(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    intent: BuyerIntent,
    position: int,
) -> IntentSuiteMember:
    now = datetime.now(UTC)
    return IntentSuiteMember(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-member:{position}"),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        buyer_intent_id=intent.id,
        position=position,
        created_at=now,
        updated_at=now,
    )


def _run(
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
    intent: BuyerIntent,
    label: str,
) -> IntentRun:
    now = datetime.now(UTC)
    return IntentRun(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-run:{label}:{intent.id}"),
        workspace_id=workspace_id,
        buyer_intent_id=intent.id,
        intent_suite_run_id=suite_run_id,
        status="completed",
        source_snapshot_hash=(
            uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-snapshot:{label}:{intent.id}").hex
            * 2
        ),
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


def _snapshot(
    *,
    index: int,
    run: IntentRun,
    status: str,
    product_index: int,
) -> PersistedMatchSnapshot:
    product_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"breakdown-product:{product_index}",
    )
    hard_constraints: tuple[ConstraintEvaluation, ...] = ()
    missing_fields: tuple[str, ...] = ()
    violated_fields: tuple[str, ...] = ()
    if status == "possible_match_missing_data":
        hard_constraints = (
            ConstraintEvaluation(
                field_key="width_mm",
                operator="equals",
                status="missing",
                expected=1,
                expected_unit="mm",
                actual=None,
                actual_unit=None,
                evidence=(),
            ),
        )
        missing_fields = ("width_mm",)
    elif status == "non_match":
        hard_constraints = (
            ConstraintEvaluation(
                field_key="width_mm",
                operator="equals",
                status="violated",
                expected=1,
                expected_unit="mm",
                actual=2,
                actual_unit="mm",
                evidence=(),
            ),
        )
        violated_fields = ("width_mm",)
    result = IntentMatchResult(
        product_id=product_id,
        variant_id=None,
        category_key="sofas",
        status=status,
        category_status="supported",
        hard_constraints=hard_constraints,
        soft_preferences=(),
        soft_score_basis_points=0,
        missing_fields=missing_fields,
        violated_fields=violated_fields,
    )
    return PersistedMatchSnapshot(
        match_id=uuid.uuid5(uuid.NAMESPACE_URL, f"breakdown-match:{index}"),
        intent_run_id=run.id,
        buyer_intent_id=run.buyer_intent_id,
        product_id=product_id,
        variant_id=None,
        result=result,
    )


def test_intent_breakdown_preserves_member_order_source_and_exact_deltas() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    current_suite_run_id = uuid.uuid4()
    previous_suite_run_id = uuid.uuid4()
    template = _intent(
        index=1,
        source="template",
        category_keys=("sofas",),
    )
    assisted = _intent(
        index=2,
        source="ai_assisted",
        category_keys=("chairs_recliners",),
    )
    template.workspace_id = workspace_id
    assisted.workspace_id = workspace_id
    members = (
        (
            _member(
                workspace_id=workspace_id,
                suite_id=suite_id,
                intent=template,
                position=0,
            ),
            template,
        ),
        (
            _member(
                workspace_id=workspace_id,
                suite_id=suite_id,
                intent=assisted,
                position=1,
            ),
            assisted,
        ),
    )
    template_current = _run(
        workspace_id=workspace_id,
        suite_run_id=current_suite_run_id,
        intent=template,
        label="current",
    )
    assisted_current = _run(
        workspace_id=workspace_id,
        suite_run_id=current_suite_run_id,
        intent=assisted,
        label="current",
    )
    template_previous = _run(
        workspace_id=workspace_id,
        suite_run_id=previous_suite_run_id,
        intent=template,
        label="previous",
    )
    assisted_previous = _run(
        workspace_id=workspace_id,
        suite_run_id=previous_suite_run_id,
        intent=assisted,
        label="previous",
    )

    items = build_intent_coverage(
        members,
        current_runs=(assisted_current, template_current),
        current_snapshots=(
            _snapshot(
                index=2,
                run=template_current,
                status="possible_match_missing_data",
                product_index=2,
            ),
            _snapshot(
                index=1,
                run=template_current,
                status="confident_match",
                product_index=1,
            ),
        ),
        previous_runs=(assisted_previous, template_previous),
        previous_snapshots=(
            _snapshot(
                index=4,
                run=template_previous,
                status="non_match",
                product_index=2,
            ),
            _snapshot(
                index=3,
                run=template_previous,
                status="possible_match_missing_data",
                product_index=1,
            ),
        ),
    )

    assert [item.member.position for item in items] == [0, 1]
    assert [item.intent.source for item in items] == ["template", "ai_assisted"]
    assert items[0].category_keys == ("sofas",)
    assert items[1].category_keys == ("chairs_recliners",)
    assert items[0].summary.target_count == 2
    assert items[0].summary.product_count == 2
    assert items[0].summary.confident_match_count == 1
    assert items[0].summary.possible_match_missing_data_count == 1
    assert items[0].summary.confident_coverage_basis_points == 5_000
    assert items[0].delta is not None
    assert items[0].delta.previous_intent_run_id == template_previous.id
    assert items[0].delta.target_count_delta == 0
    assert items[0].delta.product_count_delta == 0
    assert items[0].delta.confident_match_count_delta == 1
    assert items[0].delta.non_match_count_delta == -1
    assert items[0].delta.confident_coverage_basis_points_delta == 5_000
    assert items[1].summary.target_count == 0
    assert items[1].summary.confident_coverage_basis_points == 0
    assert items[1].delta is not None
    assert items[1].delta.confident_coverage_basis_points_delta == 0


def test_first_run_has_no_delta_and_empty_catalog_members_remain_visible() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    intent = _intent(
        index=1,
        source="user_entered",
        category_keys=(),
    )
    intent.workspace_id = workspace_id
    member = _member(
        workspace_id=workspace_id,
        suite_id=suite_id,
        intent=intent,
        position=0,
    )
    run = _run(
        workspace_id=workspace_id,
        suite_run_id=uuid.uuid4(),
        intent=intent,
        label="current",
    )

    items = build_intent_coverage(
        ((member, intent),),
        current_runs=(run,),
        current_snapshots=(),
    )

    assert len(items) == 1
    assert items[0].intent.source == "user_entered"
    assert items[0].summary.target_count == 0
    assert items[0].summary.product_count == 0
    assert items[0].summary.confident_coverage_basis_points == 0
    assert items[0].delta is None


def test_duplicate_or_missing_child_runs_fail_closed() -> None:
    workspace_id = uuid.uuid4()
    intent = _intent(
        index=1,
        source="template",
        category_keys=("sofas",),
    )
    intent.workspace_id = workspace_id
    member = _member(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        intent=intent,
        position=0,
    )
    run = _run(
        workspace_id=workspace_id,
        suite_run_id=uuid.uuid4(),
        intent=intent,
        label="current",
    )

    with pytest.raises(IntentCoverageDataError, match="duplicate child runs"):
        build_intent_coverage(
            ((member, intent),),
            current_runs=(run, run),
            current_snapshots=(),
        )
    with pytest.raises(IntentCoverageDataError, match="do not match members"):
        build_intent_coverage(
            ((member, intent),),
            current_runs=(),
            current_snapshots=(),
        )


def test_invalid_structured_intent_fails_closed() -> None:
    workspace_id = uuid.uuid4()
    intent = _intent(
        index=1,
        source="template",
        category_keys=("sofas",),
    )
    intent.workspace_id = workspace_id
    intent.structured_intent = {"query": ""}
    member = _member(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        intent=intent,
        position=0,
    )
    run = _run(
        workspace_id=workspace_id,
        suite_run_id=uuid.uuid4(),
        intent=intent,
        label="current",
    )

    with pytest.raises(IntentCoverageDataError, match="structured buyer intent"):
        build_intent_coverage(
            ((member, intent),),
            current_runs=(run,),
            current_snapshots=(),
        )


def test_intent_breakdown_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}"
        "/coverage/intents"
    )
    operation = app.openapi()["paths"][path]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/IntentCoverageByIntentResponse")
