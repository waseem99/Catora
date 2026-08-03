from catora_api.api.authority import router


def test_authority_router_contains_governed_workflow() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/v1/workspaces/{workspace_id}/authority/import-synthetic" in paths
    assert "/api/v1/workspaces/{workspace_id}/authority/accounts" in paths
    assert "/api/v1/workspaces/{workspace_id}/authority/observations" in paths
    assert "/api/v1/workspaces/{workspace_id}/authority/opportunities" in paths
    assert "/api/v1/workspaces/{workspace_id}/authority/suppressions" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/authority/opportunities/{opportunity_id}/outreach-drafts"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/authority/outreach-drafts/{draft_id}/decision"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/authority/accounts/{account_id}" in paths
    )


def test_no_authority_sending_link_purchase_or_live_provider_route_is_exposed() -> None:
    paths = {route.path for route in router.routes}
    forbidden_fragments = (
        "send",
        "publish",
        "buy-links",
        "purchase-links",
        "auto-outreach",
        "oauth",
        "connect-provider",
        "scrape-web",
    )
    assert not any(fragment in path for path in paths for fragment in forbidden_fragments)
