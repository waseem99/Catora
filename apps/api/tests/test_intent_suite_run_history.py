from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest

from catora_api.db.models.intents import IntentSuiteRun
from catora_api.intents.suite_history import (
    IntentSuiteRunHistoryDataError,
    build_suite_run_summaries,
    validated_requested_product_ids,
)


def test_suite_run_history_summaries_reconcile_independently() -> None:
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)

    summaries = build_suite_run_summaries(
        (first, second),
        member_count=3,
        status_rows=(
            (second, "non_match", 2),
            (first, "possible_match_missing_data", 1),
            (first, "confident_match", 2),
            (first, "non_match", 1),
        ),
        product_rows=((second, 1), (first, 3)),
        child_rows=((second, 3), (first, 3)),
    )

    first_summary = summaries[first]
    assert first_summary.member_count == 3
    assert first_summary.intent_run_count == 3
    assert first_summary.target_count == 4
    assert first_summary.product_count == 3
    assert first_summary.confident_match_count == 2
    assert first_summary.possible_match_missing_data_count == 1
    assert first_summary.non_match_count == 1
    assert first_summary.insufficient_category_data_count == 0
    assert first_summary.confident_coverage_basis_points == 5_000

    second_summary = summaries[second]
    assert second_summary.target_count == 2
    assert second_summary.product_count == 1
    assert second_summary.non_match_count == 2
    assert second_summary.confident_coverage_basis_points == 0


def test_suite_run_history_summary_supports_empty_catalogs() -> None:
    run_id = uuid.uuid4()

    summary = build_suite_run_summaries(
        (run_id,),
        member_count=2,
        status_rows=(),
        product_rows=(),
        child_rows=((run_id, 2),),
    )[run_id]

    assert summary.intent_run_count == 2
    assert summary.target_count == 0
    assert summary.product_count == 0
    assert summary.confident_coverage_basis_points == 0


def test_suite_run_history_rejects_duplicate_aggregate_rows() -> None:
    run_id = uuid.uuid4()

    with pytest.raises(IntentSuiteRunHistoryDataError, match="Duplicate status"):
        build_suite_run_summaries(
            (run_id,),
            member_count=1,
            status_rows=(
                (run_id, "confident_match", 1),
                (run_id, "confident_match", 1),
            ),
            product_rows=(),
            child_rows=(),
        )


def test_requested_product_selection_must_be_unique_and_canonical() -> None:
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)
    canonical = cast(
        IntentSuiteRun,
        SimpleNamespace(requested_product_ids=[str(first), str(second)]),
    )
    duplicate = cast(
        IntentSuiteRun,
        SimpleNamespace(requested_product_ids=[str(first), str(first)]),
    )
    reversed_selection = cast(
        IntentSuiteRun,
        SimpleNamespace(requested_product_ids=[str(second), str(first)]),
    )

    assert validated_requested_product_ids(canonical) == (first, second)
    with pytest.raises(IntentSuiteRunHistoryDataError, match="duplicates"):
        validated_requested_product_ids(duplicate)
    with pytest.raises(IntentSuiteRunHistoryDataError, match="canonical"):
        validated_requested_product_ids(reversed_selection)


def test_suite_run_history_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = "/api/v1/workspaces/{workspace_id}/intent-suites/{suite_id}/runs"
    operation = app.openapi()["paths"][path]["get"]

    response = operation["responses"]["200"]["content"]["application/json"]
    assert response["schema"]["$ref"].endswith("/IntentSuiteRunHistoryResponse")
    assert any(parameter["name"] == "status" for parameter in operation["parameters"])
