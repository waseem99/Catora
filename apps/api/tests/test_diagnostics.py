from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from catora_api.auth.roles import Role, can
from catora_api.diagnostics.reporting import (
    DiagnosticReport,
    IntentReport,
    build_backlog_csv,
    build_report_pptx,
)
from catora_api.diagnostics.tasks import _prepared_intents
from catora_api.main import app
from catora_api.schemas.diagnostics import DiagnosticCreateRequest, DiagnosticView


def test_diagnostic_management_is_limited_to_owner_and_admin() -> None:
    assert can(Role.OWNER, "diagnostics.manage")
    assert can(Role.ADMIN, "diagnostics.manage")
    assert not can(Role.ANALYST, "diagnostics.manage")
    assert not can(Role.REVIEWER, "diagnostics.manage")
    assert not can(Role.VIEWER, "diagnostics.manage")


def test_diagnostic_request_requires_catalog_authorization() -> None:
    with pytest.raises(ValidationError):
        DiagnosticCreateRequest(
            company_name="Lama Furniture",
            market_code="AE",
            locale="en-AE",
            currency="AED",
            retention_days=30,
            authorization_confirmed=False,
        )


def test_diagnostic_request_normalizes_market_and_storefront() -> None:
    request = DiagnosticCreateRequest(
        company_name="  Lama   Furniture ",
        market_code="ae",
        locale="en-ae",
        currency="aed",
        retention_days=30,
        authorization_confirmed=True,
        storefront_domain="https://LAMA.MYSHOPIFY.COM/",
    )
    assert request.company_name == "Lama Furniture"
    assert request.market_code == "AE"
    assert request.locale == "en-AE"
    assert request.currency == "AED"
    assert request.storefront_domain == "lama.myshopify.com"


def test_diagnostic_view_preserves_retention_and_persisted_counts() -> None:
    now = datetime.now(UTC)
    view = DiagnosticView.model_validate(
        {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "organization_id": uuid.uuid4(),
            "company_name": "Lama Furniture",
            "status": "auditing",
            "current_stage": "Running deterministic audit",
            "detail": "Evidence-backed requirements are being evaluated.",
            "market_code": "AE",
            "locale": "en-AE",
            "currency": "AED",
            "retention_expires_at": now,
            "counts": {
                "processed_rows": 2_000,
                "accepted_rows": 1_998,
                "rejected_rows": 2,
                "warning_count": 7,
                "product_count": 1_000,
                "variant_count": 2_000,
                "assigned_category_count": 950,
                "ambiguous_category_count": 30,
                "unclassified_category_count": 20,
                "finding_count": 387,
                "intent_run_count": 0,
                "intent_match_count": 0,
            },
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "failure_code": None,
            "failure_detail": None,
            "ingestion_job_id": uuid.uuid4(),
            "audit_run_id": uuid.uuid4(),
            "intent_run_ids": [],
            "result_path": "/workspace/example/diagnostic/example",
            "report_path": "/api/v1/prospect-diagnostics/example/report.pptx",
            "backlog_path": "/api/v1/prospect-diagnostics/example/backlog.csv",
            "rejection_path": "/api/v1/prospect-diagnostics/example/rejections",
        }
    )
    assert view.counts.product_count == 1_000
    assert view.counts.variant_count == 2_000
    assert view.retention_expires_at == now


def test_prepared_buyer_intents_are_deterministic_and_valid() -> None:
    market_id = uuid.uuid4()
    first = _prepared_intents(locale="en-AE", market_id=market_id)
    second = _prepared_intents(locale="en-AE", market_id=market_id)
    assert first == second
    assert len(first) == 4
    assert all(intent.market_id == market_id for _name, intent in first)


def test_branded_pptx_and_backlog_are_editable_standard_files() -> None:
    report = DiagnosticReport(
        company_name="Lama Furniture",
        market_code="AE",
        locale="en-AE",
        product_count=1_000,
        variant_count=2_000,
        processed_rows=2_000,
        rejected_rows=2,
        warning_count=7,
        assigned_categories=950,
        ambiguous_categories=30,
        unclassified_categories=20,
        score_basis_points=7_500,
        confidence_basis_points=9_800,
        finding_counts={"critical": 1, "high": 4, "medium": 10},
        top_gaps=(("Width", 120), ("Care instructions", 90)),
        findings=(),
        intents=(
            IntentReport(
                name="Compact easy-care seating",
                query="Which sofas fit a compact room and are easy to care for?",
                confident=30,
                possible_missing_data=20,
                non_match=40,
                insufficient_category=10,
            ),
        ),
    )
    pptx = build_report_pptx(report)
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        assert "ppt/slides/slide1.xml" in archive.namelist()
        first_slide = archive.read("ppt/slides/slide1.xml").decode()
        assert "Lama Furniture" in first_slide
        assert "Catora catalog assessment" in first_slide
    backlog = build_backlog_csv(report)
    assert backlog.startswith("company,market,product_id")


def test_prospect_diagnostic_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/v1/workspaces/{operator_workspace_id}/prospect-diagnostics" in paths
    assert "/api/v1/prospect-diagnostics/{assessment_id}/catalog.csv" in paths
    assert "/api/v1/prospect-diagnostics/{assessment_id}/report.pptx" in paths
    assert "/api/v1/prospect-diagnostics/{assessment_id}/backlog.csv" in paths
    assert "/api/v1/prospect-diagnostics/{assessment_id}" in paths
