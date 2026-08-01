from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from catora_api.git_publishing import (
    GitEvidenceReference,
    GitHubProvider,
    GitPatchItem,
    GitProviderCapabilities,
    GitPublishingPolicyError,
    GitRepositoryConfiguration,
    build_patch_manifest,
    normalize_repository_path,
    verify_manifest,
)

BASE_REVISION = "a" * 40
EXISTING_BLOB = "b" * 40
TREE_SHA = "c" * 40
NEW_BLOB = "d" * 40
NEW_TREE = "e" * 40
NEW_COMMIT = "f" * 40


def _configuration() -> GitRepositoryConfiguration:
    return GitRepositoryConfiguration(
        provider="github",
        repository_full_name="example/restaurant-site",
        default_branch="main",
        allowed_paths=("app/locations", "app/menu", "content"),
        protected_branches=("main", "production"),
        credential_reference="env:CATORA_TEST_GITHUB_TOKEN",
        capabilities=GitProviderCapabilities(
            can_read_repository=True,
            can_read_branches=True,
            can_create_branch=True,
            can_create_commit=True,
            can_create_pull_request=True,
        ),
    )


def _evidence() -> tuple[GitEvidenceReference, ...]:
    return (
        GitEvidenceReference(
            evidence_type="restaurant_audit_finding",
            evidence_id=uuid4(),
            checksum=hashlib.sha256(b"evidence").hexdigest(),
            observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC).isoformat(),
            source_url="https://example.test/locations/lahore",
        ),
    )


def _manifest():
    content = "export const title = 'North Grill Lahore';\n"
    return build_patch_manifest(
        configuration=_configuration(),
        base_revision=BASE_REVISION,
        proposal_branch="catora/location-title-001",
        title="Improve Lahore location title",
        body="Evidence-backed proposal. Human review and merge required.",
        items=(
            GitPatchItem(
                path="app/locations/lahore/content.ts",
                operation="update",
                content=content,
                expected_blob_sha=EXISTING_BLOB,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                evidence=_evidence(),
            ),
        ),
        rollback_plan="Revert the proposal commit or close the draft pull request.",
        idempotency_key="location-title-001",
    )


def test_repository_path_normalization_rejects_traversal_and_control_files() -> None:
    assert normalize_repository_path("app\\menu\\page.tsx") == "app/menu/page.tsx"
    for path in (
        "../.env",
        "/app/menu/page.tsx",
        ".github/workflows/deploy.yml",
        "package-lock.json",
        "infra/main.tf",
    ):
        with pytest.raises(GitPublishingPolicyError):
            normalize_repository_path(path)


def test_repository_capabilities_cannot_include_merge_or_deploy() -> None:
    with pytest.raises(ValueError, match="merge or deploy"):
        GitProviderCapabilities(
            can_read_repository=True,
            can_read_branches=True,
            can_create_branch=True,
            can_create_commit=True,
            can_create_pull_request=True,
            can_merge=True,
        )


def test_manifest_is_deterministic_and_evidence_backed() -> None:
    first = _manifest()
    second = _manifest()
    assert first == second
    verify_manifest(first)
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.items[0].evidence[0].evidence_type == "restaurant_audit_finding"


def test_manifest_rejects_non_allowlisted_or_secret_like_content() -> None:
    configuration = _configuration()
    content = "API_KEY=abcdefghijklmnop"
    item = GitPatchItem(
        path="app/admin/config.ts",
        operation="create",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        evidence=_evidence(),
    )
    with pytest.raises(GitPublishingPolicyError):
        build_patch_manifest(
            configuration=configuration,
            base_revision=BASE_REVISION,
            proposal_branch="catora/config",
            title="Unsafe proposal",
            body="Should not pass",
            items=(item,),
            rollback_plan="Close the pull request.",
            idempotency_key="unsafe",
        )


@pytest.mark.asyncio
async def test_github_provider_creates_only_branch_commit_and_draft_pr() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": BASE_REVISION}})
        if "/contents/" in path:
            return httpx.Response(200, json={"type": "file", "sha": EXISTING_BLOB})
        if path.endswith(f"/git/commits/{BASE_REVISION}"):
            return httpx.Response(200, json={"tree": {"sha": TREE_SHA}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": NEW_BLOB})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": NEW_TREE})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": NEW_COMMIT})
        if path.endswith("/git/refs"):
            payload = json.loads(request.content)
            assert payload["ref"] == "refs/heads/catora/location-title-001"
            assert payload["sha"] == NEW_COMMIT
            return httpx.Response(201, json={"ref": payload["ref"]})
        if path.endswith("/pulls"):
            payload = json.loads(request.content)
            assert payload["draft"] is True
            assert payload["base"] == "main"
            return httpx.Response(
                201,
                json={"number": 42, "html_url": "https://github.test/example/pr/42"},
            )
        raise AssertionError(f"Unexpected GitHub request: {request.method} {path}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.test",
    )
    provider = GitHubProvider(
        token="test-token-not-a-secret",
        api_base_url="https://api.github.test",
        client=client,
    )

    result = await provider.create_draft_pull_request(_configuration(), _manifest())

    assert result.number == 42
    assert result.draft is True
    assert result.submitted_revision == NEW_COMMIT
    assert not any("merge" in path or "deployment" in path for _, path in requests)
    assert "test-token-not-a-secret" not in repr(provider)
    await client.aclose()


@pytest.mark.asyncio
async def test_github_provider_fails_when_base_or_blob_changed() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "0" * 40}})
        raise AssertionError("No write should occur after stale-base detection")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token="test", client=client)
    with pytest.raises(GitPublishingPolicyError, match="changed after proposal review"):
        await provider.create_draft_pull_request(_configuration(), _manifest())
    assert call_count == 1
    await client.aclose()


def test_git_publishing_tables_are_registered_when_models_imported() -> None:
    from catora_api.db.base import Base
    from catora_api.db.models.git_publishing import (  # noqa: F401
        GitChangeProposal,
        GitRepositoryConnection,
    )

    assert "git_repository_connections" in Base.metadata.tables
    assert "git_change_proposals" in Base.metadata.tables
