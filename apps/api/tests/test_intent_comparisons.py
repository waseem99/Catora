from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

import catora_api.intents.intent_comparisons as comparison_module
from catora_api.db.models.intents import (
    BuyerIntent,
    IntentRun,
    IntentSuiteMember,
    IntentSuiteRun,
)
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    PersistedMatchSnapshot,
)
from catora_api.intents.intent_comparisons import (
    IntentCoverageByIntentComparisonService,
)
from catora_api.intents.types import (
    ConstraintEvaluation,
    IntentMatchResult,
    StructuredBuyerIntent,
)


def _intent(
    *,
    workspace_id: uuid.UUID,
    index: int,
    source: str,
    category_key: str,
) -> BuyerIntent:
    now = datetime.now(UTC)
    structured = StructuredBuyerIntent(
        query=f"Intent {index}",
        category_keys=(category_key,),
    )
    return BuyerIntent(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"comparison-intent:{index}"),
        workspace_id=workspace_id,
        lineage_id=uuid.uuid5(uuid.NAMESPACE_URL, f"comparison-lineage:{index}"),
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
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"comparison-member:{position}"),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        buyer_intent_id=intent.id,
        position=position,
        created_at=now,
        updated_at=now,
    )


def _suite_run(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    label: str,
    products: list[str],
) -> IntentSuiteRun:
    now = datetime.now(UTC)
    return IntentSuiteRun(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"comparison-suite-run:{label}"),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        previous_run_id=None,
        status="completed",
        requested_product_ids=products,
        source_snapshot_hash=("a" if label == "selected" else "b") * 64,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


def _child_run(
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
    intent: BuyerIntent,
    label: str,
) -> IntentRun:
    now = datetime.now(UTC)
    return IntentRun(
        id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"comparison-child-run:{label}:{intent.id}",
        ),
        workspace_id=workspace_id,
        buyer_intent_id=intent.id,
        intent_suite_run_id=suite_run_id,
        status="completed",
        source_snapshot_hash=(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"comparison-child-snapshot:{label}:{intent.id}",
            ).hex
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
        f"comparison-product:{product_index}",
    )
    hard_constraints: tuple[ConstraintEvaluation, ...] = ()
    violated_fields: tuple[str, ...] = ()
    if status == "non_match":
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
        missing_fields=(),
        violated_fields=violated_fields,
    )
    return PersistedMatchSnapshot(
        match_id=uuid.uuid5(uuid.NAMESPACE_URL, f"comparison-match:{index}"),
        intent_run_id=run.id,
        buyer_intent_id=run.buyer_intent_id,
        product_id=product_id,
        variant_id=None,
        result=result,
    )


@pytest.mark.asyncio
async def test_arbitrary_baseline_preserves_order_and_exact_intent_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    first_product = uuid.UUID(int=1)
    second_product = uuid.UUID(int=2)
    selected = _suite_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        label="selected",
        products=[str(first_product), str(second_product)],
    )
    baseline = _suite_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        label="baseline",
        products=[str(first_product)],
    )
    template = _intent(
        workspace_id=workspace_id,
        index=1,
        source="template",
        category_key="sofas",
    )
    assisted = _intent(
        workspace_id=workspace_id,
        index=2,
        source="ai_assisted",
        category_key="chairs_recliners",
    )
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
    selected_template = _child_run(
        workspace_id=workspace_id,
        suite_run_id=selected.id,
        intent=template,
        label="selected",
    )
    selected_assisted = _child_run(
        workspace_id=workspace_id,
        suite_run_id=selected.id,
        intent=assisted,
        label="selected",
    )
    baseline_template = _child_run(
        workspace_id=workspace_id,
        suite_run_id=baseline.id,
        intent=template,
        label="baseline",
    )
    baseline_assisted = _child_run(
        workspace_id=workspace_id,
        suite_run_id=baseline.id,
        intent=assisted,
        label="baseline",
    )

    async def fake_suite_run(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentSuiteRun:
        assert workspace_id == selected.workspace_id
        return selected if suite_run_id == selected.id else baseline

    async def fake_members(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_id: uuid.UUID,
    ) -> tuple[tuple[IntentSuiteMember, BuyerIntent], ...]:
        assert workspace_id == selected.workspace_id
        assert suite_id == selected.intent_suite_id
        return members

    async def fake_child_runs(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> tuple[IntentRun, ...]:
        assert workspace_id == selected.workspace_id
        if suite_run_id == selected.id:
            return (selected_assisted, selected_template)
        return (baseline_assisted, baseline_template)

    async def fake_snapshots(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> tuple[PersistedMatchSnapshot, ...]:
        assert workspace_id == selected.workspace_id
        if suite_run_id == selected.id:
            return (
                _snapshot(
                    index=1,
                    run=selected_template,
                    status="confident_match",
                    product_index=1,
                ),
                _snapshot(
                    index=2,
                    run=selected_template,
                    status="confident_match",
                    product_index=2,
                ),
            )
        return (
            _snapshot(
                index=3,
                run=baseline_template,
                status="non_match",
                product_index=1,
            ),
        )

    monkeypatch.setattr(comparison_module, "_suite_run", fake_suite_run)
    monkeypatch.setattr(comparison_module, "_suite_members", fake_members)
    monkeypatch.setattr(comparison_module, "_child_runs", fake_child_runs)
    monkeypatch.setattr(comparison_module, "_match_snapshots", fake_snapshots)

    report = await IntentCoverageByIntentComparisonService().compare(
        cast(Any, object()),
        workspace_id=workspace_id,
        selected_suite_run_id=selected.id,
        baseline_suite_run_id=baseline.id,
    )

    assert report.selection_changed is True
    assert [item.member.position for item in report.items] == [0, 1]
    assert [item.intent.source for item in report.items] == [
        "template",
        "ai_assisted",
    ]
    first = report.items[0]
    assert first.summary.target_count == 2
    assert first.summary.confident_match_count == 2
    assert first.summary.confident_coverage_basis_points == 10_000
    assert first.delta is not None
    assert first.delta.previous_intent_run_id == baseline_template.id
    assert first.delta.target_count_delta == 1
    assert first.delta.confident_match_count_delta == 2
    assert first.delta.non_match_count_delta == -1
    assert first.delta.confident_coverage_basis_points_delta == 10_000
    second = report.items[1]
    assert second.delta is not None
    assert second.delta.previous_intent_run_id == baseline_assisted.id
    assert second.summary.target_count == 0


@pytest.mark.asyncio
async def test_self_comparison_fails_before_database_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def unexpected_suite_run(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentSuiteRun:
        nonlocal called
        called = True
        raise AssertionError((workspace_id, suite_run_id))

    monkeypatch.setattr(comparison_module, "_suite_run", unexpected_suite_run)
    run_id = uuid.uuid4()
    with pytest.raises(IntentCoverageDataError, match="cannot be compared with itself"):
        await IntentCoverageByIntentComparisonService().compare(
            cast(Any, object()),
            workspace_id=uuid.uuid4(),
            selected_suite_run_id=run_id,
            baseline_suite_run_id=run_id,
        )
    assert called is False


@pytest.mark.asyncio
async def test_cross_suite_and_noncanonical_history_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    selected = _suite_run(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        label="selected",
        products=[],
    )
    baseline = _suite_run(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        label="baseline",
        products=[],
    )

    async def different_suites(
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentSuiteRun:
        assert workspace_id == selected.workspace_id
        return selected if suite_run_id == selected.id else baseline

    monkeypatch.setattr(comparison_module, "_suite_run", different_suites)
    service = IntentCoverageByIntentComparisonService()
    with pytest.raises(IntentCoverageDataError, match="different suites"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.id,
            baseline_suite_run_id=baseline.id,
        )

    baseline.intent_suite_id = selected.intent_suite_id
    selected.requested_product_ids = [
        str(uuid.UUID(int=2)),
        str(uuid.UUID(int=1)),
    ]
    with pytest.raises(IntentCoverageDataError, match="Selected.*canonically ordered"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.id,
            baseline_suite_run_id=baseline.id,
        )


def test_intent_comparison_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
        "compare/{baseline_run_id}/coverage/intents"
    )
    operation = app.openapi()["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith(
        "/IntentCoverageByIntentComparisonResponse"
    )
