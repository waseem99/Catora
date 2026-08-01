from catora_api.git_publishing.provider import GitHubProvider


def test_github_provider_exposes_no_merge_or_deploy_method() -> None:
    assert not hasattr(GitHubProvider, "merge")
    assert not hasattr(GitHubProvider, "deploy")
