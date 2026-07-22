from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

from catora_api.db.models.intents import IntentProductMatch, IntentSuiteRun
from catora_api.intents.coverage import (
    UNCLASSIFIED_CATEGORY_BUCKET,
    IntentCoverageDataError,
    IntentCoverageService,
    IntentCoverageStateError,
    PersistedMatchSnapshot,
    build_category_coverage,
    build_remediation_priorities,
    coverage_totals,
    filter_category_snapshots,
    persisted_match_snapshot,
)
from catora_api.intents.matcher import evaluate_intent
from catora_api.intents.types import (
    ConstraintEvaluation,
    IntentMatchResult,
    IntentProductCandidate,
    StructuredBuyerIntent,
)


def _evaluation(
    field_key: str,
    status: str,
) -> ConstraintEvaluation:
    return ConstraintEvaluation.model_validate(
        {
            "field_key": field_key,
            "operator": "equals",
            "status": status,
            "expected": True,
            "expected_unit": None,
            "actual": None,
            "actual_unit": None,
            "evidence": (),
        }
    )


def _snapshot(
    *,
    index: int,
    intent_index: int,
    product_index: int,
    category_key: str | None,
    status: str,
    fields: tuple[tuple[str, str], ...] = (),
    variant_index: int | None = None,
) -> PersistedMatchSnapshot:
    missing_fields = tuple(
        field_key
        for field_key, constraint_status in fields
        if constraint_status in {"missing", "conflicting"}
    )
    violated_fields = tuple(
        field_key
        for field_key, constraint_status in fields
        if constraint_status == "violated"
    )
    product_id = uuid.uuid5(uuid.NAMESPACE_URL, f"catora:coverage-product:{product_index}")
    variant_id = (
        uuid.uuid5(uuid.NAMESPACE_URL, f"catora:coverage-variant:{variant_index}")
        if variant_index is not None
        else None
    )
    result = IntentMatchResult.model_validate(
        {
            "product_id": product_id,
            "variant_id": variant_id,
            "category_key": category_key,
            "status": status,
            "category_status": (
                "missing"
                if status == "insufficient_category_data"
                else ("not_required" if category_key is None else "supported")
            ),
            "hard_constraints": tuple(
                _evaluation(field_key, constraint_status)
                for field_key, constraint_status in fields
            ),
            "soft_preferences": (),
            "soft_score_basis_points": 0,
            "missing_fields": missing_fields,
            "violated_fields": violated_fields,
        }
    )
    return PersistedMatchSnapshot(
        match_id=uuid.uuid5(uuid.NAMESPACE_URL, f"catora:coverage-match:{index}"),
        intent_run_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"catora:coverage-run:{intent_index}",
        ),
        buyer_intent_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"catora:coverage-intent:{intent_index}",
        ),
        product_id=product_id,
        variant_id=variant_id,
        result=result,
    )


def test_matcher_persists_supported_violated_and_missing_category_keys() -> None:
    intent = StructuredBuyerIntent(
        query="A sofa",
        category_keys=("sofas",),
    )
    product_id = uuid.uuid4()

    supported = evaluate_intent(
        intent,
        IntentProductCandidate(product_id=product_id, category_key="Sofas"),
    )
    violated = evaluate_intent(
        intent,
        IntentProductCandidate(product_id=product_id, category_key="Dining_Tables"),
    )
    missing = evaluate_intent(
        intent,
        IntentProductCandidate(product_id=product_id, category_key=None),
    )

    assert supported.category_key == "sofas"
    assert supported.category_status == "supported"
    assert violated.category_key == "dining_tables"
    assert violated.category_status == "violated"
    assert missing.category_key is None
    assert missing.category_status == "missing"


def test_category_coverage_is_reconciled_and_order_independent() -> None:
    snapshots = (
        _snapshot(
            index=1,
            intent_index=1,
            product_index=1,
            category_key="sofas",
            status="confident_match",
        ),
        _snapshot(
            index=2,
            intent_index=1,
            product_index=2,
            category_key="sofas",
            status="possible_match_missing_data",
            fields=(("width_mm", "missing"),),
        ),
        _snapshot(
            index=3,
            intent_index=2,
            product_index=1,
            category_key="sofas",
            status="non_match",
            fields=(("materials", "violated"),),
        ),
        _snapshot(
            index=4,
            intent_index=2,
            product_index=3,
            category_key=None,
            status="insufficient_category_data",
        ),
    )

    items = build_category_coverage(snapshots)
    reversed_items = build_category_coverage(tuple(reversed(snapshots)))
    totals = coverage_totals(snapshots)

    assert items == reversed_items
    assert [item.category_key for item in items] == ["sofas", None]
    sofas = items[0]
    assert sofas.intent_count == 2
    assert sofas.target_count == 3
    assert sofas.product_count == 2
    assert sofas.confident_match_count == 1
    assert sofas.possible_match_missing_data_count == 1
    assert sofas.non_match_count == 1
    assert sofas.confident_coverage_basis_points == 3_333
    assert sum(
        (
            sofas.confident_match_count,
            sofas.possible_match_missing_data_count,
            sofas.non_match_count,
            sofas.insufficient_category_data_count,
        )
    ) == sofas.target_count
    assert totals.intent_count == 2
    assert totals.target_count == 4
    assert totals.product_count == 3
    assert totals.confident_coverage_basis_points == 2_500


def test_remediation_priorities_count_targets_products_and_intents_once() -> None:
    snapshots = (
        _snapshot(
            index=1,
            intent_index=1,
            product_index=1,
            variant_index=1,
            category_key="sofas",
            status="possible_match_missing_data",
            fields=(("width_mm", "missing"),),
        ),
        _snapshot(
            index=2,
            intent_index=1,
            product_index=1,
            variant_index=2,
            category_key="sofas",
            status="possible_match_missing_data",
            fields=(("width_mm", "conflicting"),),
        ),
        _snapshot(
            index=3,
            intent_index=2,
            product_index=2,
            category_key="sofas",
            status="possible_match_missing_data",
            fields=(
                ("width_mm", "missing"),
                ("materials", "missing"),
            ),
        ),
        _snapshot(
            index=4,
            intent_index=2,
            product_index=3,
            category_key=None,
            status="possible_match_missing_data",
            fields=(("materials", "missing"),),
        ),
    )

    items = build_remediation_priorities(snapshots)
    reversed_items = build_remediation_priorities(tuple(reversed(snapshots)))

    assert items == reversed_items
    assert [item.field_key for item in items] == ["width_mm", "materials"]
    width = items[0]
    assert width.priority_rank == 1
    assert width.affected_intent_count == 2
    assert width.affected_target_count == 3
    assert width.affected_product_count == 2
    assert width.intent_impact_basis_points == 10_000
    assert width.target_impact_basis_points == 7_500
    assert width.product_impact_basis_points == 6_666
    assert width.missing_constraint_count == 2
    assert width.conflicting_constraint_count == 1
    assert width.category_keys == ("sofas",)
    assert width.unclassified_target_count == 0

    materials = items[1]
    assert materials.affected_intent_count == 1
    assert materials.affected_target_count == 2
    assert materials.affected_product_count == 2
    assert materials.unclassified_target_count == 1


def test_unclassified_category_filter_changes_scope_and_ranking() -> None:
    snapshots = (
        _snapshot(
            index=1,
            intent_index=1,
            product_index=1,
            category_key="sofas",
            status="possible_match_missing_data",
            fields=(("width_mm", "missing"),),
        ),
        _snapshot(
            index=2,
            intent_index=2,
            product_index=2,
            category_key=None,
            status="possible_match_missing_data",
            fields=(("materials", "missing"),),
        ),
    )

    selected = filter_category_snapshots(
        snapshots,
        UNCLASSIFIED_CATEGORY_BUCKET,
    )
    items = build_remediation_priorities(selected)
    scope = coverage_totals(selected)

    assert len(selected) == 1
    assert items[0].field_key == "materials"
    assert items[0].priority_rank == 1
    assert items[0].unclassified_target_count == 1
    assert scope.intent_count == 1
    assert scope.target_count == 1
    assert scope.product_count == 1


def test_persisted_explanations_fail_closed_when_category_key_is_missing() -> None:
    snapshot = _snapshot(
        index=1,
        intent_index=1,
        product_index=1,
        category_key="sofas",
        status="confident_match",
    )
    explanation = snapshot.result.model_dump(mode="json")
    explanation.pop("category_key")
    match = IntentProductMatch(
        id=snapshot.match_id,
        workspace_id=uuid.uuid4(),
        intent_run_id=snapshot.intent_run_id,
        product_id=snapshot.product_id,
        variant_id=snapshot.variant_id,
        status=snapshot.result.status,
        score=None,
        explanation=explanation,
    )

    with pytest.raises(IntentCoverageDataError, match="explanation is invalid"):
        persisted_match_snapshot(match, snapshot.buyer_intent_id)


class CoverageSession:
    def __init__(
        self,
        run: IntentSuiteRun,
        rows: list[tuple[IntentProductMatch, uuid.UUID]] | None = None,
    ) -> None:
        self.run = run
        self.rows = rows or []
        self.statement: object | None = None

    async def scalar(self, _statement: object) -> IntentSuiteRun:
        return self.run

    async def execute(self, statement: object) -> SimpleNamespace:
        self.statement = statement
        return SimpleNamespace(all=lambda: self.rows)


def _suite_run(status: str = "completed") -> IntentSuiteRun:
    return IntentSuiteRun(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        intent_suite_id=uuid.uuid4(),
        previous_run_id=None,
        status=status,
        requested_product_ids=[],
        source_snapshot_hash="a" * 64,
        started_at=None,
        completed_at=None,
    )


@pytest.mark.asyncio
async def test_service_rejects_incomplete_runs_before_loading_matches() -> None:
    run = _suite_run(status="running")
    session = CoverageSession(run)

    with pytest.raises(IntentCoverageStateError, match="not completed"):
        await IntentCoverageService().category_coverage(
            cast(Any, session),
            workspace_id=run.workspace_id,
            suite_run_id=run.id,
        )

    assert session.statement is None


@pytest.mark.asyncio
async def test_service_query_uses_only_persisted_run_and_match_tables() -> None:
    run = _suite_run()
    session = CoverageSession(run)

    report = await IntentCoverageService().category_coverage(
        cast(Any, session),
        workspace_id=run.workspace_id,
        suite_run_id=run.id,
    )

    assert report.items == ()
    assert report.totals.target_count == 0
    assert session.statement is not None
    sql = str(cast(Any, session.statement).compile(dialect=postgresql.dialect()))
    assert "intent_product_matches" in sql
    assert "intent_runs" in sql
    assert " products " not in sql
    assert " categories " not in sql


def test_coverage_openapi_contracts_are_registered() -> None:
    from catora_api.main import app

    base = "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage"
    paths = app.openapi()["paths"]

    assert paths[base + "/categories"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentCategoryCoverageResponse")
    assert paths[base + "/remediations"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentRemediationResponse")
