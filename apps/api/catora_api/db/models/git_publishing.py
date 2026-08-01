from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class GitRepositoryConnection(Base):
    __tablename__ = "git_repository_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "repository_full_name",
            name="uq_git_repository_connection_workspace_provider_repo",
        ),
        Index(
            "ix_git_repository_connections_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    protected_branches: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    capability_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class GitChangeProposal(Base):
    __tablename__ = "git_change_proposals"
    __table_args__ = (
        UniqueConstraint(
            "repository_connection_id",
            "idempotency_key",
            name="uq_git_change_proposal_connection_idempotency",
        ),
        Index(
            "ix_git_change_proposals_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("git_repository_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("change_sets.id", ondelete="SET NULL"),
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    base_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    patch_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    patch_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    rollback_plan: Mapped[str] = mapped_column(Text, nullable=False)
    conflict_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider_pr_number: Mapped[int | None] = mapped_column(Integer)
    provider_pr_url: Mapped[str | None] = mapped_column(String(2_000))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_revision: Mapped[str | None] = mapped_column(String(64))
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
