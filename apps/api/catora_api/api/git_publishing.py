from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import Membership
from catora_api.db.models.git_publishing import GitChangeProposal, GitRepositoryConnection
from catora_api.git_publishing.models import (
    GitPatchItem,
    GitProvider,
    GitProviderCapabilities,
    GitProviderPullRequest,
    GitRepositoryConfiguration,
)
from catora_api.git_publishing.policy import GitPublishingPolicyError
from catora_api.git_publishing.service import GitPublishingService

router = APIRouter(prefix="/api/v1", tags=["governed Git publishing"])


class GitPublishingApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitRepositoryCreateRequest(GitPublishingApiModel):
    provider: GitProvider
    repository_full_name: str
    default_branch: str
    allowed_paths: tuple[str, ...] = Field(min_length=1, max_length=500)
    protected_branches: tuple[str, ...] = Field(default=("main", "master"))
    credential_reference: str
    capabilities: GitProviderCapabilities


class GitRepositoryResponse(GitPublishingApiModel):
    id: uuid.UUID
    provider: str
    repository_full_name: str
    default_branch: str
    allowed_paths: list[str]
    protected_branches: list[str]
    capability_snapshot: dict[str, Any]
    status: str


class GitProposalCreateRequest(GitPublishingApiModel):
    repository_connection_id: uuid.UUID
    change_set_id: uuid.UUID | None = None
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    proposal_branch: str
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)
    items: tuple[GitPatchItem, ...] = Field(min_length=1, max_length=200)
    rollback_plan: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=1, max_length=160)


class GitProposalApproveRequest(GitPublishingApiModel):
    expected_patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class GitProposalResponse(GitPublishingApiModel):
    id: uuid.UUID
    repository_connection_id: uuid.UUID
    change_set_id: uuid.UUID | None
    requested_by_user_id: uuid.UUID
    reviewed_by_user_id: uuid.UUID | None
    base_revision: str
    proposal_branch: str
    status: str
    title: str
    body: str
    patch_hash: str
    patch_manifest: dict[str, Any]
    rollback_plan: str
    conflict_detail: dict[str, Any]
    provider_pr_number: int | None
    provider_pr_url: str | None
    published_revision: str | None
    validation_result: dict[str, Any]


class GitProposalSubmitResponse(GitPublishingApiModel):
    proposal: GitProposalResponse
    pull_request: GitProviderPullRequest


async def _membership(
    *,
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Membership:
    return await auth_service.membership(session, context.user.id, workspace_id)


def _require_repository_admin(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Repository connection management permission required")


def _require_proposal_author(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Recommendation write permission required")


def _require_human_approver(role: str) -> None:
    if Role(role) not in {Role.OWNER, Role.ADMIN}:
        raise AuthorizationError("Owner or admin approval required")


def _require_live_submission_enabled() -> None:
    if os.environ.get("CATORA_GIT_PUBLISHING_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="Git publishing is disabled")


def _repository_response(connection: GitRepositoryConnection) -> GitRepositoryResponse:
    return GitRepositoryResponse(
        id=connection.id,
        provider=connection.provider,
        repository_full_name=connection.repository_full_name,
        default_branch=connection.default_branch,
        allowed_paths=connection.allowed_paths,
        protected_branches=connection.protected_branches,
        capability_snapshot=connection.capability_snapshot,
        status=connection.status,
    )


def _proposal_response(proposal: GitChangeProposal) -> GitProposalResponse:
    return GitProposalResponse(
        id=proposal.id,
        repository_connection_id=proposal.repository_connection_id,
        change_set_id=proposal.change_set_id,
        requested_by_user_id=proposal.requested_by_user_id,
        reviewed_by_user_id=proposal.reviewed_by_user_id,
        base_revision=proposal.base_revision,
        proposal_branch=proposal.proposal_branch,
        status=proposal.status,
        title=proposal.title,
        body=proposal.body,
        patch_hash=proposal.patch_hash,
        patch_manifest=proposal.patch_manifest,
        rollback_plan=proposal.rollback_plan,
        conflict_detail=proposal.conflict_detail,
        provider_pr_number=proposal.provider_pr_number,
        provider_pr_url=proposal.provider_pr_url,
        published_revision=proposal.published_revision,
        validation_result=proposal.validation_result,
    )


@router.post(
    "/workspaces/{workspace_id}/git-repositories",
    response_model=GitRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_git_repository_connection(
    workspace_id: uuid.UUID,
    payload: GitRepositoryCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> GitRepositoryResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_repository_admin(membership.role)
    try:
        configuration = GitRepositoryConfiguration(
            provider=payload.provider,
            repository_full_name=payload.repository_full_name,
            default_branch=payload.default_branch,
            allowed_paths=payload.allowed_paths,
            protected_branches=payload.protected_branches,
            credential_reference=payload.credential_reference,
            capabilities=payload.capabilities,
        )
        connection = await GitPublishingService().create_connection(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            configuration=configuration,
        )
    except GitPublishingPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _repository_response(connection)


@router.get(
    "/workspaces/{workspace_id}/git-repositories",
    response_model=list[GitRepositoryResponse],
)
async def list_git_repository_connections(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[GitRepositoryResponse]:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(GitRepositoryConnection)
            .where(GitRepositoryConnection.workspace_id == workspace_id)
            .order_by(
                GitRepositoryConnection.repository_full_name,
                GitRepositoryConnection.id,
            )
        )
    ).all()
    return [_repository_response(row) for row in rows]


@router.post(
    "/workspaces/{workspace_id}/git-proposals",
    response_model=GitProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_git_proposal(
    workspace_id: uuid.UUID,
    payload: GitProposalCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> GitProposalResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_proposal_author(membership.role)
    try:
        proposal, _ = await GitPublishingService().create_draft_proposal(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            connection_id=payload.repository_connection_id,
            change_set_id=payload.change_set_id,
            base_revision=payload.base_revision,
            proposal_branch=payload.proposal_branch,
            title=payload.title,
            body=payload.body,
            items=payload.items,
            rollback_plan=payload.rollback_plan,
            idempotency_key=payload.idempotency_key,
        )
    except GitPublishingPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _proposal_response(proposal)


@router.post(
    "/workspaces/{workspace_id}/git-proposals/{proposal_id}/approve",
    response_model=GitProposalResponse,
)
async def approve_git_proposal(
    workspace_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: GitProposalApproveRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> GitProposalResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_human_approver(membership.role)
    try:
        proposal = await GitPublishingService().approve_proposal(
            session,
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            reviewer_user_id=context.user.id,
            expected_patch_hash=payload.expected_patch_hash,
        )
    except GitPublishingPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _proposal_response(proposal)


@router.post(
    "/workspaces/{workspace_id}/git-proposals/{proposal_id}/submit",
    response_model=GitProposalSubmitResponse,
)
async def submit_git_proposal(
    workspace_id: uuid.UUID,
    proposal_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> GitProposalSubmitResponse:
    _require_live_submission_enabled()
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_human_approver(membership.role)
    try:
        proposal, pull_request = await GitPublishingService().submit_proposal(
            session,
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            actor_user_id=context.user.id,
        )
    except GitPublishingPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GitProposalSubmitResponse(
        proposal=_proposal_response(proposal),
        pull_request=pull_request,
    )


@router.get(
    "/workspaces/{workspace_id}/git-proposals/{proposal_id}",
    response_model=GitProposalResponse,
)
async def get_git_proposal(
    workspace_id: uuid.UUID,
    proposal_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> GitProposalResponse:
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    proposal = await session.scalar(
        select(GitChangeProposal).where(
            GitChangeProposal.id == proposal_id,
            GitChangeProposal.workspace_id == workspace_id,
        )
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Git proposal not found")
    return _proposal_response(proposal)


@router.delete(
    "/workspaces/{workspace_id}/git-repositories/{connection_id}",
    response_model=GitRepositoryResponse,
)
async def disconnect_git_repository(
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> GitRepositoryResponse:
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_repository_admin(membership.role)
    try:
        connection = await GitPublishingService().disconnect_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            actor_user_id=context.user.id,
        )
    except GitPublishingPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _repository_response(connection)
