from catora_api.api.git_publishing import router


def test_governed_git_router_contains_lifecycle_routes() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/v1/workspaces/{workspace_id}/git-repositories" in paths
    assert "/api/v1/workspaces/{workspace_id}/git-proposals" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/git-proposals/{proposal_id}/approve"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/git-proposals/{proposal_id}/submit"
        in paths
    )
