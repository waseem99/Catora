from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from catora_api.db.models.intents import IntentProductMatch, IntentSuiteRun
from catora_api.intents.coverage import IntentCoverageService
from catora_api.intents.types import ConstraintEvaluation, IntentMatchResult


def _match(
    *,
    workspace_id: uuid.UUID,
    match_index: int,
    intent_index: int,
    product_index: int,
    field_keys: tuple[str, ...],
    category_key: str | None = "sofas",
) -> tuple[IntentProductMatch, uuid.UUID]:
    product_id = uuid.uuid5(uuid.NAMESPACE_URL, f"coverage-page-product:{product_index}")
    intent_run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"coverage-page-run:{intent_index}")
    buyer_intent_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coverage-page-intent:{intent_index}",
    )
    result = IntentMatchResult(
        product_id=product_id,
        variant_id=None,
        category_key=category_key,
        status="possible_match_missing_data",
        category_status="not_required" if category_key is None else "supported",
        hard_constraints=tuple(
            ConstraintEvaluation(
                field_key=field_key,
                operator="equals",
                status="missing",
                expected=True,
                expected_unit=None,
                actual=None,
                actual_unit=None,
                evidence=(),
            )
            for field_key in field_keys
        ),
        soft_preferences=(),
        soft_score_basis_points=0,
        missing_fields=field_keys,
        violated_fields=(),
    )
    return (
        IntentProductMatch(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"coverage-page-match:{match_index}"),
            workspace_id=workspace_id,
            intent_run_id=intent_run_id,
            product_id=product_id,
            variant_id=None,
            status=result.status,
            score=None,
            explanation=result.model_dump(mode="json"),
        ),
        buyer_intent_id,
    )


class CoveragePageSession:
    def __init__(
        self,
        run: IntentSuiteRun,
        rows: list[tuple[IntentProductMatch, uuid.UUID]],
    ) -> None:
        self.run = run
        self.rows = rows

    async def scalar(self, _statement: object) -> IntentSuiteRun:
        return self.run

    async def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.rows)


@pytest.mark.asyncio
async def test_remediation_page_uses_same_filtered_scope_for_totals() -> None:
    workspace_id = uuid.uuid4()
    run = IntentSuiteRun(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        intent_suite_id=uuid.uuid4(),
        previous_run_id=None,
        status="completed",
        requested_product_ids=[],
        source_snapshot_hash="a" * 64,
        started_at=None,
        completed_at=None,
    )
    rows = [
        _match(
            workspace_id=workspace_id,
            match_index=1,
            intent_index=1,
            product_index=1,
            field_keys=("width_mm",),
        ),
        _match(
            workspace_id=workspace_id,
            match_index=2,
            intent_index=2,
            product_index=2,
            field_keys=("width_mm", "materials"),
        ),
        _match(
            workspace_id=workspace_id,
            match_index=3,
            intent_index=2,
            product_index=3,
            field_keys=("materials",),
            category_key=None,
        ),
    ]
    session = CoveragePageSession(run, list(reversed(rows)))

    page = await IntentCoverageService().remediations(
        cast(Any, session),
        workspace_id=workspace_id,
        suite_run_id=run.id,
        category_bucket="sofas",
        offset=1,
        limit=1,
    )

    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].field_key == "materials"
    assert page.scope.intent_count == 2
    assert page.scope.target_count == 2
    assert page.scope.product_count == 2
