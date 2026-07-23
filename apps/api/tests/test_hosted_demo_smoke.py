from __future__ import annotations

import io
import zipfile

import pytest

from scripts import smoke_hosted_demo as smoke


def _valid_preflight() -> dict[str, object]:
    return {
        "ready": True,
        "components": [
            {"key": "database", "state": "ok"},
            {"key": "redis", "state": "ok"},
            {"key": "worker", "state": "ok"},
            {"key": "object_storage", "state": "ok"},
            {"key": "report_generation", "state": "ok"},
        ],
        "last_verified_snapshot": {
            "audit_run_id": "audit-id",
            "verified_at": "2026-07-23T00:00:00+00:00",
            "product_count": 1_000,
            "variant_count": 2_000,
        },
    }


def _valid_shopify_installation() -> dict[str, object]:
    return {
        "shop_domain": "northstar-living-demo.myshopify.com",
        "status": "active",
        "health": "healthy",
        "granted_scopes": ["read_products"],
        "token_mode": "expiring_offline",
        "sync_status": "completed",
        "product_count": 1_000,
        "variant_count": 2_000,
        "last_successful_sync_at": "2026-07-23T00:00:00+00:00",
        "last_audit_run_id": "audit-id",
    }


def test_required_does_not_modify_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATORA_SMOKE_PASSWORD", "secret-ending-in-slash/")

    assert smoke._required("CATORA_SMOKE_PASSWORD") == "secret-ending-in-slash/"


def test_preflight_requires_every_component_to_be_healthy() -> None:
    preflight = _valid_preflight()
    components = preflight["components"]
    assert isinstance(components, list)
    components[2] = {"key": "worker", "state": "warning"}

    with pytest.raises(RuntimeError, match="worker:warning"):
        smoke._validate_preflight(preflight)


def test_preflight_requires_exact_demo_scale() -> None:
    preflight = _valid_preflight()
    snapshot = preflight["last_verified_snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["product_count"] = 999

    with pytest.raises(RuntimeError, match="scale mismatch"):
        smoke._validate_preflight(preflight)


def test_shopify_acceptance_requires_exact_scope_and_sync() -> None:
    installation = _valid_shopify_installation()
    result = smoke._validate_shopify_installation(installation)
    assert result["product_count"] == 1_000
    assert result["variant_count"] == 2_000

    installation["granted_scopes"] = ["read_products", "write_products"]
    with pytest.raises(RuntimeError, match="read_products"):
        smoke._validate_shopify_installation(installation)


def test_pptx_validation_requires_editable_office_parts() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "content-types")
        archive.writestr("ppt/presentation.xml", "presentation")
        archive.writestr("ppt/slides/slide1.xml", "slide")

    result = smoke._validate_pptx(
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    assert result["slide_count"] == 1

    with pytest.raises(RuntimeError, match="valid Office package"):
        smoke._validate_pptx(b"not-a-zip", "application/vnd.ms-powerpoint.presentation")


def test_csv_validation_requires_findings_and_recommendations() -> None:
    header = (
        "product_id,product_title,record_type,severity_or_state,field_key,"
        "current_value,proposed_or_remediation,evidence,verification_required\n"
    )
    payload = (
        header
        + "1,Sofa,finding,high,width_mm,,add width,evidence,\n"
        + "1,Sofa,recommendation,pending,width_mm,,2100,evidence,true\n"
    ).encode()

    result = smoke._validate_csv(payload, "text/csv; charset=utf-8")
    assert result["row_count"] == 2

    findings_only = (header + "1,Sofa,finding,high,width_mm,,add width,evidence,\n").encode()
    with pytest.raises(RuntimeError, match="finding and recommendation"):
        smoke._validate_csv(findings_only, "text/csv")
