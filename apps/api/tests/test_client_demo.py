from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime

from catora_api.demo.pptx import build_demo_pptx
from catora_api.main import app
from catora_api.schemas.demo import DemoOverviewResponse


def _overview() -> DemoOverviewResponse:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    recommendation_id = uuid.uuid4()
    return DemoOverviewResponse.model_validate(
        {
            "workspace_id": workspace_id,
            "workspace_name": "Northstar Living",
            "generated_at": datetime.now(UTC),
            "catalog": {
                "product_count": 100,
                "variant_count": 200,
                "attribute_count": 500,
                "image_count": 100,
            },
            "audit": {
                "run_id": uuid.uuid4(),
                "score_basis_points": 6840,
                "confidence_basis_points": 9130,
                "critical_count": 0,
                "high_count": 12,
                "medium_count": 24,
            },
            "top_gaps": [
                {
                    "field_key": "width_mm",
                    "label": "Product width",
                    "affected_products": 8,
                }
            ],
            "hero_product": {
                "id": product_id,
                "title": "Compact sofa",
                "canonical_key": "demo:compact-sofa",
                "category_key": "sofas",
                "source_evidence": [],
            },
            "findings": [
                {
                    "id": uuid.uuid4(),
                    "product_id": product_id,
                    "product_title": "Compact sofa",
                    "severity": "high",
                    "title": "Missing product width",
                    "explanation": "Width is missing.",
                    "category_key": "sofas",
                    "field_key": "width_mm",
                    "business_impact": "discoverability",
                    "remediation_type": "add_structured_attribute",
                    "evidence": [],
                }
            ],
            "intent": {
                "id": uuid.uuid4(),
                "name": "Compact apartment sofa",
                "query": "Which sofas fit a compact apartment?",
                "confident_match_count": 4,
                "possible_match_count": 1,
                "non_match_count": 5,
                "insufficient_category_count": 0,
                "hero_product_before_status": "possible_match_missing_data",
                "hero_product_after_status": "confident_match",
                "missing_fields": ["width_mm"],
                "explanation": "Width is missing.",
            },
            "recommendation": {
                "id": recommendation_id,
                "product_id": product_id,
                "product_title": "Compact sofa",
                "status": "ready_for_review",
                "source_snapshot_hash": "a" * 64,
                "fields": [],
            },
            "change_set": {
                "id": None,
                "name": None,
                "status": "not_created",
                "approved_field_count": 0,
                "rejected_field_count": 0,
                "export_ready": False,
            },
            "report_pptx_path": f"/api/v1/workspaces/{workspace_id}/demo/report.pptx",
            "operational_csv_path": f"/api/v1/workspaces/{workspace_id}/demo/backlog.csv",
        }
    )


def test_demo_pptx_is_valid_office_package() -> None:
    payload = build_demo_pptx(_overview())
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names
        assert "ppt/slides/slide1.xml" in names
        assert "ppt/slides/slide6.xml" in names


def test_demo_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/workspaces/{workspace_id}/demo" in paths
    assert "/api/v1/workspaces/{workspace_id}/demo/report.pptx" in paths
    assert "/api/v1/workspaces/{workspace_id}/demo/backlog.csv" in paths
