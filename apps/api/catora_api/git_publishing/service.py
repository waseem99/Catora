from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.git_publishing import (
    GitChangeProposal,
    GitRepositoryConnection,
)
from catora_api.git_publishing.models import (
    GitPatchItem,
    GitPatchManifest,
    GitProvider,
    GitProviderCapabilities,
    GitProviderPullRequest,
    GitRepositoryConfiguration,
)
from catora_api.git_publishing.policy import (
    GitPublishingPolicyError,
    build_patch_manifest,
)
from catora_api.git_publishing.provider import (
    GitHostingProvider,
    GitHubProvider,
    GitProviderError,
)


class CredentialResolver(Protocol):
    def resolve(self, reference: str) -> str: ...


class EnvironmentCredentialResolver:
    def resolve(self, reference: str) -> str:
        if not reference.startswith("env:"):
            raise GitPublishingPolicyError("Credential reference scheme is unsupported")
        name = reference.removeprefix("env:")
        if not name or not name.replace("_", "").isalnum() or name.upper() != name:
            raise GitPublishingPolicyError("Credential environment variable name is invalid")
        value = os.environ.get(name)
        if not value:
            raise GitPublishingPolicyError("Git provider credential is unavailable")
        return value


class GitProviderFactory:
    def __init__(self, resolver: CredentialResolver | None = None) -> None:
        self._resolver = resolver or EnvironmentCredentialResolver()

    def create(
        self,
        configuration: GitRepositoryConfiguration,
    ) -> GitHostingProvider:
        token = self._resolver.resolve(configuration.credential_reference)
        if configuration.provider == "github":
            return GitHubProvider(token=token)
        raise GitPublishingPolicyError(
            f"Provider '{configuration.provider}' is not enabled in this runtime"
        )


class GitPublishingService:
    async def create_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        configuration: GitRepositoryConfiguration,
    ) -> GitRepositoryConnection:
        existing = await session.scalar(
            select(GitRepositoryConnection).where(
                GitRepositoryConnection.workspace_id == workspace_id,
                GitRepositoryConnection.provider == configuration.provider,
                GitRepositoryConnection.repository_full_name
                == configuration.repository_full_name,
            )
        )
        if existing is not None:
            raise GitPublishingPolicyError("Repository connection already exists")
        connection = GitRepositoryConnection(
            workspace_id=workspace_id,
            provider=configuration.provider,
            repository_full_name=configuration.repository_full_name,
            default_branch=configuration.default_branch,
            allowed_paths=list(configuration.allowed_paths),
            protected_branches=list(configuration.protected_branches),
            credential_reference=configuration.credential_reference,
            capability_snapshot=configuration.capabilities.model_dump(mode="json"),
            status="ready",
        )
        session.add(connection)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="git.repository_connected",
                entity_type="git_repository_connection",
                entity_id=connection.id,
                payload={
                    "provider": configuration.provider,
                    "repository_full_name": configuration.repository_full_name,
                    "default_branch": configuration.default_branch,
                    "allowed_path_count": len(configuration.allowed_paths),
                    "capabilities": configuration.capabilities.model_dump(mode="json"),
                },
            )
        )
        await session.commit()
        return connection

    async def create_draft_proposal(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        connection_id: uuid.UUID,
        base_revision: str,
        proposal_branch: str,
        title: str,
        body: str,
        items: tuple[GitPatchItem, ...],
        rollback_plan: str,
        idempotency_key: str,
        change_set_id: uuid.UUID | None = None,
    ) -> tuple[GitChangeProposal, GitPatchManifest]:
        connection = await self._connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
        )
        existing = await session.scalar(
            select(GitChangeProposal).where(
                GitChangeProposal.repository_connection_id == connection.id,
                GitChangeProposal.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            manifest = GitPatchManifest.model_validate(existing.patch_manifest)
            return existing, manifest
        manifest = build_patch_manifest(
            configuration=self._configuration(connection),
            base_revision=base_revision,
            proposal_branch=proposal_branch,
            title=title,
            body=body,
            items=items,
            rollback_plan=rollback_plan,
            idempotency_key=idempotency_key,
        )
        evidence = [
            reference.model_dump(mode="json", exclude_none=True)
            for item in manifest.items
            for reference in item.evidence
        ]
        proposal = GitChangeProposal(
            workspace_id=workspace_id,
            repository_connection_id=connection.id,
            change_set_id=change_set_id,
            requested_by_user_id=actor_user_id,
            base_revision=manifest.base_revision,
            proposal_branch=manifest.proposal_branch,
            idempotency_key=manifest.idempotency_key,
            status="draft",
            title=manifest.title,
            body=manifest.body,
            patch_manifest=manifest.model_dump(mode="json", exclude_none=True),
            patch_hash=manifest.manifest_sha256,
            source_evidence=evidence,
            rollback_plan=manifest.rollback_plan,
            conflict_detail={},
            validation_result={},
        )
        session.add(proposal)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="git.proposal_created",
                entity_type="git_change_proposal",
                entity_id=proposal.id,
                payload={
                    "repository_connection_id": str(connection.id),
                    "repository_full_name": connection.repository_full_name,
                    "base_revision": manifest.base_revision,
                    "proposal_branch": manifest.proposal_branch,
                    "patch_hash": manifest.manifest_sha256,
                    "item_count": len(manifest.items),
                },
            )
        )
        await session.commit()
        return proposal, manifest

    async def approve_proposal(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        proposal_id: uuid.UUID,
        reviewer_user_id: uuid.UUID,
        expected_patch_hash: str,
    ) -> GitChangeProposal:
        proposal = await self._proposal(
            session,
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            lock=True,
        )
        if proposal.patch_hash != expected_patch_hash:
            raise GitPublishingPolicyError("Proposal changed after review")
        if proposal.status == "approved":
            return proposal
        if proposal.status != "draft":
            raise GitPublishingPolicyError("Only draft proposals can be approved")
        proposal.status = "approved"
        proposal.reviewed_by_user_id = reviewer_user_id
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=reviewer_user_id,
                event_type="git.proposal_approved",
                entity_type="git_change_proposal",
                entity_id=proposal.id,
                payload={"patch_hash": proposal.patch_hash},
            )
        )
        await session.commit()
        return proposal

    async def submit_proposal(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        proposal_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        provider_factory: GitProviderFactory | None = None,
    ) -> tuple[GitChangeProposal, GitProviderPullRequest]:
        proposal = await self._proposal(
            session,
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            lock=True,
        )
        if proposal.status == "submitted":
            return proposal, await self._submitted_pull_request(
                session,
                workspace_id=workspace_id,
                proposal=proposal,
            )
        if proposal.status != "approved" or proposal.reviewed_by_user_id is None:
            raise GitPublishingPolicyError("Proposal requires explicit human approval")
        connection = await self._connection(
            session,
            workspace_id=workspace_id,
            connection_id=proposal.repository_connection_id,
        )
        configuration = self._configuration(connection)
        manifest = GitPatchManifest.model_validate(proposal.patch_manifest)
        provider = (provider_factory or GitProviderFactory()).create(configuration)
        try:
            pull_request = await provider.create_draft_pull_request(configuration, manifest)
        except (GitPublishingPolicyError, GitProviderError) as exc:
            proposal.status = "conflict"
            proposal.conflict_detail = {
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
            }
            await session.commit()
            raise
        proposal.status = "submitted"
        proposal.provider_pr_number = pull_request.number
        proposal.provider_pr_url = pull_request.url
        proposal.submitted_at = datetime.now(UTC)
        proposal.published_revision = pull_request.submitted_revision
        proposal.conflict_detail = {}
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="git.proposal_submitted",
                entity_type="git_change_proposal",
                entity_id=proposal.id,
                payload={
                    "provider": pull_request.provider,
                    "repository_full_name": pull_request.repository_full_name,
                    "pull_request_number": pull_request.number,
                    "proposal_branch": pull_request.head_branch,
                    "base_branch": pull_request.base_branch,
                    "base_revision": pull_request.base_revision,
                    "submitted_revision": pull_request.submitted_revision,
                    "draft": True,
                },
            )
        )
        await session.commit()
        return proposal, pull_request

    async def disconnect_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> GitRepositoryConnection:
        connection = await self._connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            lock=True,
        )
        connection.status = "disconnected"
        connection.disconnected_at = datetime.now(UTC)
        connection.credential_reference = "revoked"
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="git.repository_disconnected",
                entity_type="git_repository_connection",
                entity_id=connection.id,
                payload={
                    "provider": connection.provider,
                    "repository_full_name": connection.repository_full_name,
                },
            )
        )
        await session.commit()
        return connection

    async def _submitted_pull_request(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        proposal: GitChangeProposal,
    ) -> GitProviderPullRequest:
        if (
            proposal.provider_pr_number is None
            or proposal.provider_pr_url is None
            or proposal.published_revision is None
        ):
            raise GitPublishingPolicyError("Submitted proposal provider state is incomplete")
        connection = await self._connection(
            session,
            workspace_id=workspace_id,
            connection_id=proposal.repository_connection_id,
        )
        return GitProviderPullRequest(
            provider=cast(GitProvider, connection.provider),
            repository_full_name=connection.repository_full_name,
            number=proposal.provider_pr_number,
            url=proposal.provider_pr_url,
            head_branch=proposal.proposal_branch,
            base_branch=connection.default_branch,
            base_revision=proposal.base_revision,
            submitted_revision=proposal.published_revision,
            draft=True,
        )

    async def _connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        lock: bool = False,
    ) -> GitRepositoryConnection:
        statement = select(GitRepositoryConnection).where(
            GitRepositoryConnection.id == connection_id,
            GitRepositoryConnection.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        connection = await session.scalar(statement)
        if connection is None:
            raise GitPublishingPolicyError("Repository connection not found")
        if connection.status != "ready":
            raise GitPublishingPolicyError("Repository connection is not active")
        return connection

    async def _proposal(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        proposal_id: uuid.UUID,
        lock: bool = False,
    ) -> GitChangeProposal:
        statement = select(GitChangeProposal).where(
            GitChangeProposal.id == proposal_id,
            GitChangeProposal.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        proposal = await session.scalar(statement)
        if proposal is None:
            raise GitPublishingPolicyError("Git proposal not found")
        return proposal

    @staticmethod
    def _configuration(
        connection: GitRepositoryConnection,
    ) -> GitRepositoryConfiguration:
        return GitRepositoryConfiguration(
            provider=cast(GitProvider, connection.provider),
            repository_full_name=connection.repository_full_name,
            default_branch=connection.default_branch,
            allowed_paths=tuple(connection.allowed_paths),
            protected_branches=tuple(connection.protected_branches),
            credential_reference=connection.credential_reference,
            capabilities=GitProviderCapabilities.model_validate(
                connection.capability_snapshot
            ),
        )
