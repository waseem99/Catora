from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field

from catora_api.git_publishing.models import (
    GitPatchManifest,
    GitProviderCapabilities,
    GitProviderPullRequest,
    GitRepositoryConfiguration,
)
from catora_api.git_publishing.policy import GitPublishingPolicyError, verify_manifest


class GitProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RepositoryFileState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    exists: bool
    blob_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class GitHostingProvider(Protocol):
    async def capabilities(
        self,
        configuration: GitRepositoryConfiguration,
    ) -> GitProviderCapabilities: ...

    async def branch_revision(
        self,
        configuration: GitRepositoryConfiguration,
        branch: str,
    ) -> str: ...

    async def file_state(
        self,
        configuration: GitRepositoryConfiguration,
        *,
        path: str,
        revision: str,
    ) -> RepositoryFileState: ...

    async def create_draft_pull_request(
        self,
        configuration: GitRepositoryConfiguration,
        manifest: GitPatchManifest,
    ) -> GitProviderPullRequest: ...


@dataclass(slots=True)
class GitHubProvider:
    token: str
    api_base_url: str = "https://api.github.com"
    client: httpx.AsyncClient | None = None

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("GitHub provider token is required")
        self.api_base_url = self.api_base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"GitHubProvider(api_base_url={self.api_base_url!r}, token=<redacted>)"

    async def __aenter__(self) -> Self:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=20.0)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def capabilities(
        self,
        configuration: GitRepositoryConfiguration,
    ) -> GitProviderCapabilities:
        if configuration.provider != "github":
            raise GitProviderError("GitHub provider cannot serve another provider type")
        repository = await self._request(
            "GET",
            f"/repos/{configuration.repository_full_name}",
        )
        permissions = repository.get("permissions")
        can_push = isinstance(permissions, dict) and bool(permissions.get("push"))
        return GitProviderCapabilities(
            can_read_repository=True,
            can_read_branches=True,
            can_create_branch=can_push,
            can_create_commit=can_push,
            can_create_pull_request=can_push,
            can_merge=False,
            can_deploy=False,
        )

    async def branch_revision(
        self,
        configuration: GitRepositoryConfiguration,
        branch: str,
    ) -> str:
        payload = await self._request(
            "GET",
            f"/repos/{configuration.repository_full_name}/git/ref/heads/{branch}",
        )
        object_value = payload.get("object")
        sha = object_value.get("sha") if isinstance(object_value, dict) else None
        if not isinstance(sha, str) or len(sha) != 40:
            raise GitProviderError("Repository branch response did not contain a commit SHA")
        return sha

    async def file_state(
        self,
        configuration: GitRepositoryConfiguration,
        *,
        path: str,
        revision: str,
    ) -> RepositoryFileState:
        try:
            payload = await self._request(
                "GET",
                f"/repos/{configuration.repository_full_name}/contents/{path}",
                params={"ref": revision},
            )
        except GitProviderError as exc:
            if exc.status_code == 404:
                return RepositoryFileState(path=path, exists=False)
            raise
        sha = payload.get("sha")
        file_type = payload.get("type")
        if file_type != "file" or not isinstance(sha, str) or len(sha) != 40:
            raise GitProviderError("Repository content path is not a regular file")
        return RepositoryFileState(path=path, exists=True, blob_sha=sha)

    async def create_draft_pull_request(
        self,
        configuration: GitRepositoryConfiguration,
        manifest: GitPatchManifest,
    ) -> GitProviderPullRequest:
        if configuration.provider != "github":
            raise GitProviderError("GitHub provider cannot serve another provider type")
        if manifest.repository_full_name != configuration.repository_full_name:
            raise GitPublishingPolicyError("Manifest repository does not match its connection")
        verify_manifest(manifest)
        current_revision = await self.branch_revision(
            configuration,
            configuration.default_branch,
        )
        if current_revision != manifest.base_revision:
            raise GitPublishingPolicyError(
                "Repository default branch changed after proposal review"
            )
        for item in manifest.items:
            state = await self.file_state(
                configuration,
                path=item.path,
                revision=manifest.base_revision,
            )
            if item.operation == "create" and state.exists:
                raise GitPublishingPolicyError(
                    f"Create target '{item.path}' already exists at the reviewed revision"
                )
            if item.operation == "update" and (
                not state.exists or state.blob_sha != item.expected_blob_sha
            ):
                raise GitPublishingPolicyError(
                    f"Update target '{item.path}' changed after review"
                )
        base_commit = await self._request(
            "GET",
            f"/repos/{configuration.repository_full_name}/git/commits/{manifest.base_revision}",
        )
        tree_value = base_commit.get("tree")
        base_tree_sha = tree_value.get("sha") if isinstance(tree_value, dict) else None
        if not isinstance(base_tree_sha, str) or len(base_tree_sha) != 40:
            raise GitProviderError("Base commit did not include a tree SHA")
        tree_entries: list[dict[str, str]] = []
        for item in manifest.items:
            blob = await self._request(
                "POST",
                f"/repos/{configuration.repository_full_name}/git/blobs",
                json_body={
                    "content": base64.b64encode(item.content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blob_sha = blob.get("sha")
            if not isinstance(blob_sha, str) or len(blob_sha) != 40:
                raise GitProviderError("Created blob did not include a SHA")
            tree_entries.append(
                {
                    "path": item.path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )
        tree = await self._request(
            "POST",
            f"/repos/{configuration.repository_full_name}/git/trees",
            json_body={"base_tree": base_tree_sha, "tree": tree_entries},
        )
        tree_sha = tree.get("sha")
        if not isinstance(tree_sha, str) or len(tree_sha) != 40:
            raise GitProviderError("Created tree did not include a SHA")
        commit = await self._request(
            "POST",
            f"/repos/{configuration.repository_full_name}/git/commits",
            json_body={
                "message": manifest.title,
                "tree": tree_sha,
                "parents": [manifest.base_revision],
            },
        )
        commit_sha = commit.get("sha")
        if not isinstance(commit_sha, str) or len(commit_sha) != 40:
            raise GitProviderError("Created proposal commit did not include a SHA")
        await self._request(
            "POST",
            f"/repos/{configuration.repository_full_name}/git/refs",
            json_body={
                "ref": f"refs/heads/{manifest.proposal_branch}",
                "sha": commit_sha,
            },
        )
        pull_request = await self._request(
            "POST",
            f"/repos/{configuration.repository_full_name}/pulls",
            json_body={
                "title": manifest.title,
                "body": manifest.body,
                "head": manifest.proposal_branch,
                "base": configuration.default_branch,
                "draft": True,
                "maintainer_can_modify": True,
            },
        )
        number = pull_request.get("number")
        url = pull_request.get("html_url")
        if not isinstance(number, int) or not isinstance(url, str):
            raise GitProviderError("Created pull request response was incomplete")
        return GitProviderPullRequest(
            provider="github",
            repository_full_name=configuration.repository_full_name,
            number=number,
            url=url,
            head_branch=manifest.proposal_branch,
            base_branch=configuration.default_branch,
            base_revision=manifest.base_revision,
            submitted_revision=commit_sha,
            draft=True,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self.client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=20.0)
        try:
            response = await client.request(
                method,
                f"{self.api_base_url}{path}",
                params=params,
                json=json_body,
                headers={
                    "accept": "application/vnd.github+json",
                    "authorization": f"Bearer {self.token}",
                    "x-github-api-version": "2022-11-28",
                    "user-agent": "catora-governed-git-publishing",
                },
            )
        except httpx.HTTPError as exc:
            raise GitProviderError("Git provider request failed") from exc
        finally:
            if owns_client:
                await client.aclose()
        if not response.is_success:
            raise GitProviderError(
                f"Git provider request failed with status {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitProviderError("Git provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise GitProviderError("Git provider response must be an object")
        return payload
