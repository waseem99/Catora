from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from catora_api.db.models.intents import IntentSuiteMember, IntentSuiteRun
from catora_api.intents.suites import (
    IntentSuiteMemberError,
    IntentSuiteMemberRecord,
    IntentSuiteRecord,
    IntentSuiteRunSummary,
    coverage_basis_points,
    suite_snapshot_hash,
    summary_delta,
)
from catora_api.schemas.intent_suites import (
    IntentSuiteCreateRequest,
    IntentSuiteMemberRequest,
    IntentSuiteRunCreateRequest,
)


def test_suite_schemas_reject_duplicate_members_and_products() -> None:
    lineage_id = uuid.uuid4()
    member = IntentSuiteMemberRequest(lineage_id=lineage_id, intent_version=2)
    with pytest.raises(ValidationError, match="suite members must be unique"):
        IntentSuiteCreateRequest(name="Suite", members=(member, member))

    product_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="product_ids must be unique"):
        IntentSuiteRunCreateRequest(product_ids=(product_id, product_id))


def test_coverage_and_delta_use_explicit_deterministic_denominators() -> None:
    assert coverage_basis_points(0, 0) == 0
    assert coverage_basis_points(1, 3) == 3333
    assert coverage_basis_points(3, 3) == 10_000

    previous_run_id = uuid.uuid4()
    previous = IntentSuiteRunSummary(
        member_count=2,
        intent_run_count=2,
        target_count=10,
        product_count=5,
        confident_match_count=4,
        possible_match_missing_data_count=3,
        non_match_count=2,
        insufficient_category_data_count=1,
        confident_coverage_basis_points=4000,
    )
    current = IntentSuiteRunSummary(
        member_count=2,
        intent_run_count=2,
        target_count=10,
        product_count=5,
        confident_match_count=6,
        possible_match_missing_data_count=2,
        non_match_count=1,
        insufficient_category_data_count=1,
        confident_coverage_basis_points=6000,
    )

    delta = summary_delta(previous_run_id, current, previous)
    assert delta.previous_run_id == previous_run_id
    assert delta.confident_match_count_delta == 2
    assert delta.possible_match_missing_data_count_delta == -1
    assert delta.non_match_count_delta == -1
    assert delta.confident_coverage_basis_points_delta == 2000


def test_suite_snapshot_is_ordered_deterministic_and_version_sensitive() -> None:
    suite_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    first_intent_id = uuid.uuid4()
    second_intent_id = uuid.uuid4()
    first_lineage = uuid.uuid4()
    second_lineage = uuid.uuid4()

    suite = SimpleNamespace(id=suite_id, workspace_id=workspace_id)
    first_member = SimpleNamespace(position=0)
    second_member = SimpleNamespace(position=1)
    first_intent = SimpleNamespace(
        id=first_intent_id,
        lineage_id=first_lineage,
        version=1,
    )
    second_intent = SimpleNamespace(
        id=second_intent_id,
        lineage_id=second_lineage,
        version=3,
    )
    record = IntentSuiteRecord(
        suite=cast(Any, suite),
        members=(
            IntentSuiteMemberRecord(
                member=cast(Any, first_member),
                intent=cast(Any, first_intent),
            ),
            IntentSuiteMemberRecord(
                member=cast(Any, second_member),
                intent=cast(Any, second_intent),
            ),
        ),
    )
    children = (
        SimpleNamespace(run=SimpleNamespace(source_snapshot_hash="a" * 64)),
        SimpleNamespace(run=SimpleNamespace(source_snapshot_hash="b" * 64)),
    )
    first_product = uuid.uuid4()
    second_product = uuid.uuid4()

    first_hash = suite_snapshot_hash(
        record,
        product_ids=(second_product, first_product),
        child_runs=cast(Any, children),
    )
    same_hash = suite_snapshot_hash(
        record,
        product_ids=(first_product, second_product),
        child_runs=cast(Any, children),
    )
    assert first_hash == same_hash
    assert len(first_hash) == 64

    changed_intent = SimpleNamespace(
        id=second_intent_id,
        lineage_id=second_lineage,
        version=4,
    )
    changed_record = IntentSuiteRecord(
        suite=cast(Any, suite),
        members=(
            record.members[0],
            IntentSuiteMemberRecord(
                member=cast(Any, second_member),
                intent=cast(Any, changed_intent),
            ),
        ),
    )
    assert suite_snapshot_hash(
        changed_record,
        product_ids=(first_product, second_product),
        child_runs=cast(Any, children),
    ) != first_hash

    with pytest.raises(IntentSuiteMemberError, match="one child run per member"):
        suite_snapshot_hash(record, product_ids=(), child_runs=cast(Any, children[:1]))


def test_suite_model_constraints_protect_positions_members_and_statuses() -> None:
    member_names = {constraint.name for constraint in IntentSuiteMember.__table__.constraints}
    run_names = {constraint.name for constraint in IntentSuiteRun.__table__.constraints}
    assert "ck_intent_suite_members_valid_position" in member_names
    assert "ck_intent_suite_runs_valid_status" in run_names

    member_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in IntentSuiteMember.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("intent_suite_id", "position") in member_unique_columns
    assert ("intent_suite_id", "buyer_intent_id") in member_unique_columns


def test_intent_suite_openapi_contracts_are_registered() -> None:
    from catora_api.main import app

    collection = "/api/v1/workspaces/{workspace_id}/intent-suites"
    detail = collection + "/{suite_id}"
    run_collection = detail + "/runs"
    run_detail = "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}"
    paths = app.openapi()["paths"]

    assert paths[collection]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentSuiteView")
    assert paths[run_collection]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentSuiteRunView")
    assert paths[run_detail]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/IntentSuiteRunView")


def test_migration_revision_is_stacked_after_buyer_intent_versions() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic/versions/0015_add_intent_suites.py"
    spec = importlib.util.spec_from_file_location("intent_suite_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "0015"
    assert module.down_revision == "0014"
