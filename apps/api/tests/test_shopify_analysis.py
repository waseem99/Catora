from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.db.models import IngestionJob, ReportJob
from catora_api.shopify.analysis import (
    SHOPIFY_ANALYSIS_TEMPLATE_VERSION,
    _intent_definitions,
    should_run_shopify_analysis,
    verified_shopify_analysis_report,
)


def installation(*, verified: bool = False) -> ReportJob:
    snapshot: dict[str, object] = {
        "distribution": "public",
        "shop_domain": "prospect-store.myshopify.com",
    }
    if verified:
        snapshot["last_verified_analysis_report_job_id"] = str(uuid.uuid4())
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status="active",
        input_snapshot=snapshot,
        template_version="shopify-public-installation-v1",
    )


def ingestion_job(
    *,
    reason: str,
    success_count: int = 0,
    full_reconciliation: bool = False,
) -> IngestionJob:
    return IngestionJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        catalog_source_id=uuid.uuid4(),
        status="completed",
        success_count=success_count,
        checkpoint={
            "shopify": {
                "reason": reason,
                "full_reconciliation": full_reconciliation,
            }
        },
    )


def test_initial_shopify_sync_always_runs_analysis() -> None:
    assert should_run_shopify_analysis(
        installation(verified=False),
        ingestion_job(reason="public_app_activation"),
    )


def test_empty_incremental_reconciliation_reuses_verified_analysis() -> None:
    assert not should_run_shopify_analysis(
        installation(verified=True),
        ingestion_job(reason="scheduled_incremental_reconciliation"),
    )


@pytest.mark.parametrize(
    "reason",
    [
        "embedded_app_manual",
        "products/create",
        "products/update",
        "products/delete",
    ],
)
def test_explicit_or_product_change_sync_refreshes_analysis(reason: str) -> None:
    assert should_run_shopify_analysis(
        installation(verified=True),
        ingestion_job(reason=reason),
    )


def test_full_reconciliation_refreshes_analysis_even_without_changed_rows() -> None:
    assert should_run_shopify_analysis(
        installation(verified=True),
        ingestion_job(
            reason="scheduled_full_reconciliation",
            full_reconciliation=True,
        ),
    )


def test_prepared_shopify_intents_are_bounded_and_deterministic() -> None:
    market_id = uuid.uuid4()
    first = _intent_definitions(locale="en-US", market_id=market_id)
    second = _intent_definitions(locale="en-US", market_id=market_id)

    assert [item[0] for item in first] == [
        "compact-easy-care-seating",
        "six-seat-dining",
        "low-maintenance-outdoor-furniture",
        "small-space-storage",
    ]
    assert [item[2].model_dump(mode="json") for item in first] == [
        item[2].model_dump(mode="json") for item in second
    ]
    assert all(item[2].market_id == market_id for item in first)
    assert all(item[2].locale == "en-US" for item in first)


class ReportSession:
    def __init__(self, report: ReportJob | None) -> None:
        self.report = report

    async def get(self, _model: object, _identifier: object) -> ReportJob | None:
        return self.report


@pytest.mark.asyncio
async def test_verified_report_must_match_workspace_type_status_and_template() -> None:
    app_installation = installation(verified=False)
    report_id = uuid.uuid4()
    app_installation.input_snapshot = {
        **dict(app_installation.input_snapshot),
        "last_verified_analysis_report_job_id": str(report_id),
    }
    report = ReportJob(
        id=report_id,
        workspace_id=app_installation.workspace_id,
        report_type="prospect_diagnostic",
        status="completed",
        input_snapshot={
            "company_name": "Prospect Store",
            "market_code": "US",
            "locale": "en-US",
        },
        template_version=SHOPIFY_ANALYSIS_TEMPLATE_VERSION,
    )

    resolved = await verified_shopify_analysis_report(
        cast(Any, ReportSession(report)),
        app_installation,
    )
    assert resolved is report

    report.status = "failed"
    assert (
        await verified_shopify_analysis_report(
            cast(Any, ReportSession(report)),
            app_installation,
        )
        is None
    )


def test_analysis_report_snapshot_does_not_need_credentials() -> None:
    report = ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="prospect_diagnostic",
        status="completed",
        input_snapshot={
            "company_name": "Prospect Store",
            "market_code": "US",
            "locale": "en-US",
            "completed_at": datetime.now(UTC).isoformat(),
            "intent_run_ids": [],
        },
        template_version=SHOPIFY_ANALYSIS_TEMPLATE_VERSION,
    )
    serialized = str(report.input_snapshot).casefold()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
