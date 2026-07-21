from __future__ import annotations

import pytest
from pydantic import ValidationError

from catora_api.api.audits import router as audits_router
from catora_api.auth.roles import Role, can
from catora_api.main import app
from catora_api.schemas.audits import AuditRunCreateRequest, AuditRunView


def test_audit_execution_capability_matches_existing_analysis_roles() -> None:
    assert can(Role.OWNER, "analysis.run")
    assert can(Role.ADMIN, "analysis.run")
    assert can(Role.ANALYST, "analysis.run")
    assert not can(Role.REVIEWER, "analysis.run")
    assert not can(Role.VIEWER, "analysis.run")


def test_audit_request_accepts_supported_modes_and_rejects_unknown_inputs() -> None:
    assert AuditRunCreateRequest(mode="full").mode == "full"
    assert AuditRunCreateRequest(mode="incremental").mode == "incremental"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AuditRunCreateRequest.model_validate(
            {
                "taxonomy_version": "1.0.0",
                "mode": "full",
                "unknown": True,
            }
        )

    with pytest.raises(ValidationError):
        AuditRunCreateRequest.model_validate(
            {"taxonomy_version": "1.0.0", "mode": "partial"}
        )


def test_internal_snapshot_hash_map_is_not_exposed() -> None:
    assert "product_snapshot_hashes" not in AuditRunView.model_fields


def test_audit_routes_are_mounted_with_expected_methods() -> None:
    expected = {
        "/api/v1/workspaces/{workspace_id}/audit-runs": {"get", "post"},
        "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}": {"get"},
        "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}/cancel": {"post"},
        "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}/findings": {"get"},
    }
    router_paths = {route.path for route in audits_router.routes}
    openapi_paths = app.openapi()["paths"]

    assert set(expected) <= router_paths
    for path, methods in expected.items():
        assert path in openapi_paths
        assert set(openapi_paths[path]) == methods
