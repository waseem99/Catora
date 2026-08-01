from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
)


class RestaurantAnswerSuiteVersion(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_answer_suite_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "suite_key", "suite_version"),
        UniqueConstraint("workspace_id", "suite_sha256"),
    )

    suite_key: Mapped[str] = mapped_column(String(100), nullable=False)
    suite_version: Mapped[str] = mapped_column(String(100), nullable=False)
    suite_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class RestaurantAnswerRun(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_answer_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key"),
        Index(
            "ix_restaurant_answer_runs_workspace_entity_created",
            "workspace_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
    )

    suite_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_answer_suite_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class RestaurantAnswerResult(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_answer_results"
    __table_args__ = (
        UniqueConstraint("run_id", "question_key"),
        Index(
            "ix_restaurant_answer_results_workspace_state",
            "workspace_id",
            "state",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_answer_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_key: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    fact_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RestaurantExternalCitationObservation(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_external_citation_observations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "response_sha256",
            "observed_at",
        ),
        Index(
            "ix_restaurant_external_citation_workspace_provider_observed",
            "workspace_id",
            "provider",
            "observed_at",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_or_surface: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(50), nullable=False)
    exact_query: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cited_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    accuracy_state: Mapped[str] = mapped_column(String(40), nullable=False)
    verified_fact_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    provider_cost_microunits: Mapped[int | None] = mapped_column(Integer)
