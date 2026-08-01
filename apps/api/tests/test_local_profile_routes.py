from catora_api.api.local_profiles import router


def test_local_profile_router_contains_read_only_inventory_lifecycle() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/v1/workspaces/{workspace_id}/local-profile-accounts" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/local-profile-accounts/{account_id}/sync-synthetic"
        in paths
    )
    assert "/api/v1/workspaces/{workspace_id}/local-profile-observations" in paths
    assert "/api/v1/workspaces/{workspace_id}/local-profile-links" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/local-profile-links/{link_id}" in paths
    )
    assert "/api/v1/workspaces/{workspace_id}/local-profile-conflicts" in paths


def test_no_google_profile_mutation_route_is_exposed() -> None:
    paths = {route.path for route in router.routes}
    forbidden_fragments = (
        "create-profile",
        "update-profile",
        "verify-profile",
        "transfer-ownership",
        "appeal-suspension",
    )
    assert not any(fragment in path for path in paths for fragment in forbidden_fragments)
