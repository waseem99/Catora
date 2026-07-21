from __future__ import annotations

import pytest
from pydantic import ValidationError

from catora_api.api.taxonomy import router as taxonomy_router
from catora_api.auth.roles import Role, can
from catora_api.main import app
from catora_api.schemas.taxonomy import AssignProductCategoriesRequest


def test_taxonomy_management_is_admin_only() -> None:
    assert can(Role.OWNER, "catalog.taxonomy.manage")
    assert can(Role.ADMIN, "catalog.taxonomy.manage")
    assert not can(Role.ANALYST, "catalog.taxonomy.manage")
    assert not can(Role.REVIEWER, "catalog.taxonomy.manage")
    assert not can(Role.VIEWER, "catalog.taxonomy.manage")


def test_assignment_request_rejects_duplicate_secondary_categories() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        AssignProductCategoriesRequest(
            taxonomy_version="1.0.0",
            primary_category_key="sofas_sectionals",
            secondary_category_keys=["lighting", "lighting"],
            reason="Manual review",
        )


def test_assignment_request_rejects_primary_as_secondary() -> None:
    with pytest.raises(ValidationError, match="cannot also be"):
        AssignProductCategoriesRequest(
            taxonomy_version="1.0.0",
            primary_category_key="sofas_sectionals",
            secondary_category_keys=["sofas_sectionals"],
            reason="Manual review",
        )


def test_taxonomy_routes_are_mounted_with_expected_methods() -> None:
    expected = {
        "/api/v1/workspaces/{workspace_id}/taxonomy/compile": {"post"},
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/category-preview": {"get"},
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/category-assignment": {
            "get",
            "put",
        },
    }
    router_paths = {route.path for route in taxonomy_router.routes}
    openapi_paths = app.openapi()["paths"]

    assert set(expected) <= router_paths
    for path, methods in expected.items():
        assert path in openapi_paths
        assert set(openapi_paths[path]) == methods
