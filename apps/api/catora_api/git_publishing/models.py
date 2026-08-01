from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

GIT_PUBLISHING_CONTRACT_VERSION: Literal["git-publishing/v1"] = "git-publishing/v1"

GitProvider = Literal["github", "gitlab", "bitbucket"]
GitOperation = Literal["create", "update"]
GitProposalStatus = Literal[
    "draft",
    "approved",
    "conflict",
    "submitted",
    "closed",
    "published_verified",
    "cancelled",
]


class GitPublishingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GitProviderCapabilities(GitPublishingModel):
    can_read_repository: bool
    can_read_branches: bool
    can_create_branch: bool
    can_create_commit: bool
    can_create_pull_request: bool
    can_merge: bool = False
    can_deploy: bool = False
    tested_at: str | None = None

    @model_validator(mode="after")
    def validate_safety(self) -> GitProviderCapabilities:
        if self.can_merge or self.can_deploy:
            raise ValueError("Catora Git publishing capabilities cannot include merge or deploy")
        return self


class GitRepositoryConfiguration(GitPublishingModel):
    provider: GitProvider
    repository_full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    default_branch: str = Field(min_length=1, max_length=255)
    allowed_paths: tuple[str, ...] = Field(min_length=1, max_length=500)
    protected_branches: tuple[str, ...] = Field(default=("main", "master"), max_length=100)
    credential_reference: str = Field(min_length=1, max_length=500)
    capabilities: GitProviderCapabilities

    @model_validator(mode="after")
    def validate_configuration(self) -> GitRepositoryConfiguration:
        if self.default_branch not in self.protected_branches:
            raise ValueError("Default branch must be protected")
        if len(self.allowed_paths) != len(set(self.allowed_paths)):
            raise ValueError("Allowed repository paths must be unique")
        if len(self.protected_branches) != len(set(self.protected_branches)):
            raise ValueError("Protected branches must be unique")
        return self


class GitEvidenceReference(GitPublishingModel):
    evidence_type: str = Field(min_length=1, max_length=100)
    evidence_id: UUID | None = None
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: str
    source_url: str | None = Field(default=None, max_length=2_000)


class GitPatchItem(GitPublishingModel):
    path: str = Field(min_length=1, max_length=1_000)
    operation: GitOperation
    content: str = Field(max_length=1_000_000)
    expected_blob_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[GitEvidenceReference, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_operation(self) -> GitPatchItem:
        if self.operation == "update" and self.expected_blob_sha is None:
            raise ValueError("Update operations require the expected current blob SHA")
        if self.operation == "create" and self.expected_blob_sha is not None:
            raise ValueError("Create operations cannot include an existing blob SHA")
        return self


class GitPatchManifest(GitPublishingModel):
    contract_version: Literal["git-publishing/v1"] = GIT_PUBLISHING_CONTRACT_VERSION
    repository_full_name: str
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    proposal_branch: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)
    items: tuple[GitPatchItem, ...] = Field(min_length=1, max_length=200)
    rollback_plan: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=1, max_length=160)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_paths(self) -> GitPatchManifest:
        paths = [item.path for item in self.items]
        if len(paths) != len(set(paths)):
            raise ValueError("A Git proposal cannot change the same path more than once")
        return self


class GitProviderPullRequest(GitPublishingModel):
    provider: GitProvider
    repository_full_name: str
    number: int = Field(gt=0)
    url: str
    head_branch: str
    base_branch: str
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    submitted_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    draft: bool = True


class GitPostPublishValidation(GitPublishingModel):
    published_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verified_by_user_id: UUID
    checks: dict[str, Literal["passed", "failed", "unavailable"]]
    evidence: tuple[GitEvidenceReference, ...] = ()
    notes: str | None = Field(default=None, max_length=20_000)
