from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from catora_api.intents.coverage import IntentCoverageDataError
from catora_api.intents.match_transitions import (
    IntentMatchEvidence,
    build_match_transitions,
)
from catora_api.intents.types import (
    ConstraintEvaluation,
    IntentMatchResult,
    IntentMatchStatus,
)


def _result(
    *,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    status: IntentMatchStatus,
    score: int,
    category_key: str | None = "sofas",
) -> IntentMatchResult:
    constraints: tuple[ConstraintEvaluation, ...] = ()
    missing_fields: tuple[str, ...] = ()
    violated_fields: tuple[str, ...] = ()
    category_status = "supported"
    if status == "possible_match_missing_data":
        constraints = (
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
        constraints = (
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
    elif status == "insufficient_category_data":
        category_key = None
        category_status = "missing"
    return IntentMatchResult(
        product_id=product_id,
        variant_id=variant_id,
        category_key=category_key,
        status=status,
        category_status=category_status,
        hard_constraints=constraints,
        soft_preferences=(),
        soft_score_basis_points=score,
        missing_fields=missing_fields,
        violated_fields=violated_fields,
    )


def _evidence(
    *,
    index: int,
    run_label: str,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None = None,
    status: IntentMatchStatus = "confident_match",
    score: int = 0,
    category_key: str | None = "sofas",
) -> IntentMatchEvidence:
    return IntentMatchEvidence(
        match_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"transition-match:{run_label}:{index}",
        ),
        intent_run_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"transition-run:{run_label}",
        ),
        product_id=product_id,
        variant_id=variant_id,
        status=status,
        soft_score_basis_points=score,
        explanation=_result(
            product_id=product_id,
            variant_id=variant_id,
            status=status,
            score=score,
            category_key=category_key,
        ),
        created_at=datetime.now(UTC),
    )


def test_transition_union_order_and_change_flags() -> None:
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)
    third = uuid.UUID(int=3)
    fourth = uuid.UUID(int=4)
    fifth = uuid.UUID(int=5)
    variant = uuid.UUID(int=100)
    selected = (
        _evidence(
            index=1,
            run_label="selected",
            product_id=first,
            status="confident_match",
            score=9_000,
        ),
        _evidence(
            index=2,
            run_label="selected",
            product_id=second,
            status="confident_match",
            score=7_000,
            category_key="chairs",
        ),
        _evidence(
            index=3,
            run_label="selected",
            product_id=third,
            status="confident_match",
            score=5_000,
        ),
        _evidence(
            index=4,
            run_label="selected",
            product_id=fourth,
            status="possible_match_missing_data",
        ),
        _evidence(
            index=5,
            run_label="selected",
            product_id=fourth,
            variant_id=variant,
            status="confident_match",
            score=8_000,
        ),
    )
    baseline = (
        _evidence(
            index=1,
            run_label="baseline",
            product_id=first,
            status="non_match",
        ),
        _evidence(
            index=2,
            run_label="baseline",
            product_id=second,
            status="confident_match",
            score=6_000,
            category_key="chairs",
        ),
        _evidence(
            index=3,
            run_label="baseline",
            product_id=third,
            status="confident_match",
            score=5_000,
        ),
        _evidence(
            index=6,
            run_label="baseline",
            product_id=fifth,
            status="non_match",
        ),
    )

    items, total = build_match_transitions(
        selected,
        baseline,
        selected_status=None,
        baseline_status=None,
        changed_only=True,
        offset=0,
        limit=100,
    )

    assert total == 5
    assert [(item.product_id, item.variant_id) for item in items] == [
        (first, None),
        (second, None),
        (fourth, None),
        (fourth, variant),
        (fifth, None),
    ]
    assert [item.presence for item in items] == [
        "retained",
        "retained",
        "added",
        "added",
        "removed",
    ]
    assert items[0].status_changed is True
    assert items[0].soft_score_basis_points_delta == 9_000
    assert items[0].evidence_changed is True
    assert items[1].status_changed is False
    assert items[1].soft_score_basis_points_delta == 1_000
    assert items[1].evidence_changed is False
    assert all(item.changed for item in items)


def test_filters_pagination_and_unchanged_targets_reconcile() -> None:
    products = tuple(uuid.UUID(int=index) for index in range(1, 5))
    selected = tuple(
        _evidence(
            index=index,
            run_label="selected-filter",
            product_id=product_id,
            status="confident_match",
            score=index * 1_000,
        )
        for index, product_id in enumerate(products, start=1)
    )
    baseline = (
        selected[0],
        replace(
            selected[1],
            match_id=uuid.uuid4(),
            intent_run_id=uuid.uuid4(),
            status="possible_match_missing_data",
            soft_score_basis_points=0,
            explanation=_result(
                product_id=products[1],
                variant_id=None,
                status="possible_match_missing_data",
                score=0,
            ),
        ),
        selected[2],
    )

    items, total = build_match_transitions(
        selected,
        baseline,
        selected_status="confident_match",
        baseline_status=None,
        changed_only=False,
        offset=1,
        limit=2,
    )

    assert total == 4
    assert len(items) == 2
    assert [item.product_id for item in items] == [products[1], products[2]]
    assert items[0].status_changed is True
    assert items[1].changed is False

    changed, changed_total = build_match_transitions(
        selected,
        baseline,
        selected_status="confident_match",
        baseline_status="possible_match_missing_data",
        changed_only=True,
        offset=0,
        limit=100,
    )
    assert changed_total == 1
    assert changed[0].product_id == products[1]


def test_duplicate_and_unreconciled_targets_fail_closed() -> None:
    product_id = uuid.uuid4()
    item = _evidence(
        index=1,
        run_label="invalid",
        product_id=product_id,
    )
    with pytest.raises(IntentCoverageDataError, match="duplicate targets"):
        build_match_transitions(
            (item, item),
            (),
            selected_status=None,
            baseline_status=None,
            changed_only=False,
            offset=0,
            limit=100,
        )

    invalid = replace(
        item,
        explanation=_result(
            product_id=uuid.uuid4(),
            variant_id=None,
            status="confident_match",
            score=0,
        ),
    )
    with pytest.raises(IntentCoverageDataError, match="product identity"):
        build_match_transitions(
            (invalid,),
            (),
            selected_status=None,
            baseline_status=None,
            changed_only=False,
            offset=0,
            limit=100,
        )


def test_match_transition_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
        "compare/{baseline_run_id}/intents/{buyer_intent_id}/match-transitions"
    )
    operation = app.openapi()["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/IntentMatchTransitionResponse")
