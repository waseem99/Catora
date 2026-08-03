from catora_api.main import app


def test_generic_restaurant_pilot_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{pilot_key}",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}/checks/{check_key}",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}/checks",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}/readiness",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}/decisions",
        "/api/v1/workspaces/{workspace_id}/restaurant-pilots/plans/{plan_id}/disconnect-runs",
    }
    assert expected.issubset(paths)


def test_pilot_api_exposes_no_activation_or_production_mutation_routes() -> None:
    paths = {
        path
        for path in app.openapi()["paths"]
        if "/restaurant-pilots/" in path
    }
    forbidden_fragments = {
        "/activate",
        "/connect",
        "/sync-production",
        "/source-write",
        "/provider-write",
        "/publish",
        "/merge",
        "/deploy",
        "/orders",
        "/prices",
        "/availability",
        "/reviews/post",
        "/outreach/send",
    }
    assert all(
        fragment not in path
        for path in paths
        for fragment in forbidden_fragments
    )


def test_pilot_contract_is_generic_not_ranchers_specific() -> None:
    schemas = app.openapi()["components"]["schemas"]
    plan = schemas["RestaurantPilotPlan"]
    properties = plan["properties"]
    assert "pilot_key" in properties
    assert "client_reference" in properties
    assert "ranchers" not in str(plan).casefold()
    assert "live_activation_allowed" not in properties


def test_decision_contract_cannot_request_live_activation() -> None:
    schema = app.openapi()["components"]["schemas"]["PilotAcceptanceDecision"]
    properties = schema["properties"]
    assert properties["live_activation_performed"]["const"] is False
    assert "activate" not in str(properties["decision"]).casefold()
