from catora_api.api.reputation import router


def test_reputation_router_is_registered_without_provider_mutations() -> None:
    paths = {route.path for route in router.routes}
    assert (
        "/api/v1/workspaces/{workspace_id}/review-observations/import-synthetic"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/review-observations/{review_id}/response-drafts"
        in paths
    )
    assert "/api/v1/workspaces/{workspace_id}/review-analyses" in paths
    forbidden_fragments = (
        "post-response",
        "publish-response",
        "delete-review",
        "solicit-review",
        "review-gating",
    )
    assert not any(fragment in path for path in paths for fragment in forbidden_fragments)
