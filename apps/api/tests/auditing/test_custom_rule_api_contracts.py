from __future__ import annotations

from catora_api.api.audit_rules import router as audit_rules_router
from catora_api.auth.roles import Role, can
from catora_api.main import app
from catora_api.schemas.audit_rules import (
    CustomAuditRuleCreateRequest,
    CustomAuditRuleView,
)


def test_custom_rule_routes_are_mounted_without_mutation_endpoints() -> None:
    path = "/api/v1/workspaces/{workspace_id}/audit-rules"
    router_paths = {route.path for route in audit_rules_router.routes}
    openapi_paths = app.openapi()["paths"]

    assert path in router_paths
    assert set(openapi_paths[path]) == {"get", "post"}


def test_custom_rule_authoring_is_owner_admin_only() -> None:
    assert can(Role.OWNER, "catalog.taxonomy.manage")
    assert can(Role.ADMIN, "catalog.taxonomy.manage")
    assert not can(Role.ANALYST, "catalog.taxonomy.manage")
    assert not can(Role.REVIEWER, "catalog.taxonomy.manage")
    assert not can(Role.VIEWER, "catalog.taxonomy.manage")


def test_custom_rule_contract_exposes_only_closed_dsl_fields() -> None:
    assert set(CustomAuditRuleCreateRequest.model_fields) == {
        "key",
        "name",
        "description",
        "taxonomy_version",
        "category_key",
        "field_key",
        "relationship",
        "related_field_key",
        "severity",
    }
    assert set(CustomAuditRuleView.model_fields) == {
        "rule_definition_id",
        "rule_version_id",
        "workspace_id",
        "key",
        "name",
        "description",
        "taxonomy_version",
        "category_key",
        "field_key",
        "relationship",
        "related_field_key",
        "severity",
        "is_immutable",
    }
