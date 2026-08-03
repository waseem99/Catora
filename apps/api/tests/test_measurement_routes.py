from catora_api.api.measurement import router


def test_measurement_router_contains_governed_aggregate_lifecycle() -> None:
    paths = {route.path for route in router.routes}
    assert (
        "/api/v1/workspaces/{workspace_id}/measurements/import-synthetic" in paths
    )
    assert "/api/v1/workspaces/{workspace_id}/measurements/accounts" in paths
    assert "/api/v1/workspaces/{workspace_id}/measurements/observations" in paths
    assert "/api/v1/workspaces/{workspace_id}/measurements/attributions" in paths
    assert "/api/v1/workspaces/{workspace_id}/measurements/annotations" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/measurements/accounts/{account_id}"
        in paths
    )


def test_no_live_provider_or_user_level_measurement_route_is_exposed() -> None:
    paths = {route.path for route in router.routes}
    forbidden_fragments = (
        "oauth",
        "google-search-console/connect",
        "ga4/connect",
        "user-events",
        "sessions",
        "orders",
        "transactions",
        "publish",
    )
    assert not any(fragment in path for path in paths for fragment in forbidden_fragments)
