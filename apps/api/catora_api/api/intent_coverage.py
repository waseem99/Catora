from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.coverage import (
    IntentCategoryCoverage,
    IntentCategoryCoverageReport,
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageService,
    IntentCoverageStateError,
    IntentCoverageTotals,
    IntentRemediationPage,
    IntentRemediationPriority,
)
from catora_api.schemas.intent_coverage import (
    IntentCategoryCoverageResponse,
    IntentCategoryCoverageView,
    IntentCoverageTotalsView,
    IntentRemediationPriorityView,
    IntentRemediationResponse,
)

router = APIRouter(tags=["buyer intent coverage"])
coverage_service = IntentCoverageService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/categories",
    response_model=IntentCategoryCoverageResponse,
)
async def get_intent_category_coverage(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentCategoryCoverageResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        report = await coverage_service.category_coverage(
            session,
            workspace_id=workspace_id,
            suite_run_id=run_id,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _category_report_view(report)


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/remediations",
    response_model=IntentRemediationResponse,
)
async def get_intent_remediations(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    category_bucket: Annotated[
        str | None,
        Query(
            pattern=r"^(_unclassified|[a-z][a-z0-9_]*)$",
            max_length=150,
        ),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> IntentRemediationResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        page = await coverage_service.remediations(
            session,
            workspace_id=workspace_id,
            suite_run_id=run_id,
            category_bucket=category_bucket,
            offset=offset,
            limit=limit,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _remediation_page_view(page, offset=offset, limit=limit)


def _category_report_view(
    report: IntentCategoryCoverageReport,
) -> IntentCategoryCoverageResponse:
    return IntentCategoryCoverageResponse(
        suite_run_id=report.run.id,
        source_snapshot_hash=cast(str, report.run.source_snapshot_hash),
        items=[_category_view(item) for item in report.items],
        total=len(report.items),
        totals=_totals_view(report.totals),
    )


def _category_view(item: IntentCategoryCoverage) -> IntentCategoryCoverageView:
    return IntentCategoryCoverageView(
        category_key=item.category_key,
        intent_count=item.intent_count,
        target_count=item.target_count,
        product_count=item.product_count,
        confident_match_count=item.confident_match_count,
        possible_match_missing_data_count=(
            item.possible_match_missing_data_count
        ),
        non_match_count=item.non_match_count,
        insufficient_category_data_count=(
            item.insufficient_category_data_count
        ),
        confident_coverage_basis_points=item.confident_coverage_basis_points,
    )


def _remediation_page_view(
    page: IntentRemediationPage,
    *,
    offset: int,
    limit: int,
) -> IntentRemediationResponse:
    return IntentRemediationResponse(
        suite_run_id=page.run.id,
        source_snapshot_hash=cast(str, page.run.source_snapshot_hash),
        category_bucket=page.category_bucket,
        items=[_remediation_view(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
        scope=_totals_view(page.scope),
    )


def _remediation_view(
    item: IntentRemediationPriority,
) -> IntentRemediationPriorityView:
    return IntentRemediationPriorityView(
        priority_rank=item.priority_rank,
        field_key=item.field_key,
        affected_intent_count=item.affected_intent_count,
        affected_target_count=item.affected_target_count,
        affected_product_count=item.affected_product_count,
        intent_impact_basis_points=item.intent_impact_basis_points,
        target_impact_basis_points=item.target_impact_basis_points,
        product_impact_basis_points=item.product_impact_basis_points,
        missing_constraint_count=item.missing_constraint_count,
        conflicting_constraint_count=item.conflicting_constraint_count,
        category_keys=item.category_keys,
        unclassified_target_count=item.unclassified_target_count,
    )


def _totals_view(totals: IntentCoverageTotals) -> IntentCoverageTotalsView:
    return IntentCoverageTotalsView(
        intent_count=totals.intent_count,
        target_count=totals.target_count,
        product_count=totals.product_count,
        confident_match_count=totals.confident_match_count,
        possible_match_missing_data_count=(
            totals.possible_match_missing_data_count
        ),
        non_match_count=totals.non_match_count,
        insufficient_category_data_count=(
            totals.insufficient_category_data_count
        ),
        confident_coverage_basis_points=totals.confident_coverage_basis_points,
    )
