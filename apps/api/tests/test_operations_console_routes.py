from catora_api.main import app


def test_authority_and_operations_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/v1/workspaces/{workspace_id}/authority/opportunities" in paths
    assert "/api/v1/workspaces/{workspace_id}/operations-console/snapshots" in paths
    assert "/api/v1/workspaces/{workspace_id}/operations-console/alerts" in paths
    assert "/api/v1/workspaces/{workspace_id}/operations-console/actions" in paths
    assert "/api/v1/workspaces/{workspace_id}/operations-console/monitor-runs" in paths


def test_operations_console_exposes_no_mutation_or_notification_sender_routes() -> None:
    paths = {
        path
        for path in app.openapi()["paths"]
        if "/operations-console/" in path or path.endswith("/operations-console")
    }
    forbidden_fragments = {
        "/fix",
        "/publish",
        "/deploy",
        "/send",
        "/provider-connect",
        "/order",
        "/availability",
        "/merge",
    }
    assert all(
        fragment not in path
        for path in paths
        for fragment in forbidden_fragments
    )


def test_snapshot_generation_accepts_scope_not_caller_supplied_metrics() -> None:
    schema = app.openapi()
    operation = schema["paths"][
        "/api/v1/workspaces/{workspace_id}/operations-console/snapshots"
    ]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    referenced = body_schema["$ref"].split("/")[-1]
    properties = schema["components"]["schemas"][referenced]["properties"]
    assert set(properties) == {"brand_id", "location_id"}
