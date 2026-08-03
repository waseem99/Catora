from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.config import get_settings
from catora_api.db.models import AuditEvent, Membership
from catora_api.db.models.reputation import (
    ReviewAnalysisRecord,
    ReviewObservationRecord,
    ReviewProviderAccount,
    ReviewResponseDraftRecord,
)
from catora_api.reputation import ReviewObservation, analyze_review, draft_review_response
from catora_api.reputation.models import ReviewState

router = APIRouter(prefix="/api/v1", tags=["review reputation intelligence"])
_VALID_REVIEW_STATES = {"published", "updated", "deleted", "unavailable"}


class ReputationApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewImportRequest(ReputationApiModel):
    provider_account_id: uuid.UUID
    observations: tuple[ReviewObservation, ...] = Field(max_length=5_000)


class ReviewImportResponse(ReputationApiModel):
    accepted: int
    duplicate: int
    analyzed: int
    escalated: int


class ReviewDraftRequest(ReputationApiModel):
    restaurant_name: str = Field(min_length=1, max_length=500)


class ReviewDraftResponse(ReputationApiModel):
    id: uuid.UUID
    review_observation_id: uuid.UUID
    status: str
    draft_text: str
    policy_version: str
    requires_human_approval: bool = True
    posting_allowed: bool = False


async def _membership(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Membership:
    return await auth_service.membership(session, context.user.id, workspace_id)


def _require_enabled() -> None:
    if not get_settings().reputation_intelligence_enabled:
        raise HTTPException(status_code=503, detail="Reputation intelligence is disabled")


def _require_writer(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Reputation intelligence write permission required")


def _validated_review_state(value: str) -> ReviewState:
    if value not in _VALID_REVIEW_STATES:
        raise HTTPException(
            status_code=500,
            detail="Persisted review observation contains an invalid review state",
        )
    return cast(ReviewState, value)


@router.post(
    "/workspaces/{workspace_id}/review-observations/import-synthetic",
    response_model=ReviewImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_synthetic_reviews(
    workspace_id: uuid.UUID,
    payload: ReviewImportRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ReviewImportResponse:
    _require_enabled()
    membership = await _membership(workspace_id, session, auth_service, context)
    _require_writer(membership.role)
    account = await session.scalar(
        select(ReviewProviderAccount).where(
            ReviewProviderAccount.id == payload.provider_account_id,
            ReviewProviderAccount.workspace_id == workspace_id,
        )
    )
    if account is None or account.provider != "synthetic" or account.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="Only an active synthetic review provider is accepted",
        )
    accepted = duplicate = analyzed = escalated = 0
    for observation in payload.observations:
        existing = await session.scalar(
            select(ReviewObservationRecord).where(
                ReviewObservationRecord.provider_account_id == account.id,
                ReviewObservationRecord.external_review_id
                == observation.external_review_id,
                ReviewObservationRecord.observation_hash
                == observation.observation_hash,
            )
        )
        if existing is not None:
            duplicate += 1
            continue
        await session.execute(
            update(ReviewObservationRecord)
            .where(
                ReviewObservationRecord.provider_account_id == account.id,
                ReviewObservationRecord.external_review_id
                == observation.external_review_id,
                ReviewObservationRecord.is_current.is_(True),
            )
            .values(is_current=False)
        )
        row = ReviewObservationRecord(
            workspace_id=workspace_id,
            provider_account_id=account.id,
            restaurant_location_id=observation.restaurant_location_id,
            external_location_id=observation.external_location_id,
            external_review_id=observation.external_review_id,
            rating=observation.rating,
            text=observation.text,
            language=observation.language,
            reviewer_display_name=observation.reviewer_display_name,
            provider_response_text=observation.provider_response_text,
            provider_response_updated_at=observation.provider_response_updated_at,
            review_created_at=observation.review_created_at,
            review_updated_at=observation.review_updated_at,
            review_state=observation.review_state,
            observation_hash=observation.observation_hash,
            is_current=True,
            observed_at=observation.observed_at,
        )
        session.add(row)
        await session.flush()
        accepted += 1
        analysis = analyze_review(observation)
        session.add(
            ReviewAnalysisRecord(
                workspace_id=workspace_id,
                review_observation_id=row.id,
                analysis_version=analysis.analysis_version,
                themes=list(analysis.themes),
                praise=list(analysis.praise),
                concerns=list(analysis.concerns),
                risk_level=analysis.risk_level,
                escalation_reasons=list(analysis.escalation_reasons),
                evidence={"terms": list(analysis.evidence_terms)},
                fingerprint=analysis.fingerprint,
            )
        )
        analyzed += 1
        if analysis.escalation_reasons:
            escalated += 1
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="reputation.synthetic_import_completed",
            entity_type="review_provider_account",
            entity_id=account.id,
            payload={
                "accepted": accepted,
                "duplicate": duplicate,
                "analyzed": analyzed,
                "escalated": escalated,
            },
        )
    )
    await session.commit()
    return ReviewImportResponse(
        accepted=accepted,
        duplicate=duplicate,
        analyzed=analyzed,
        escalated=escalated,
    )


@router.post(
    "/workspaces/{workspace_id}/review-observations/{review_id}/response-drafts",
    response_model=ReviewDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_response_draft(
    workspace_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: ReviewDraftRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ReviewDraftResponse:
    _require_enabled()
    membership = await _membership(workspace_id, session, auth_service, context)
    _require_writer(membership.role)
    review = await session.scalar(
        select(ReviewObservationRecord).where(
            ReviewObservationRecord.id == review_id,
            ReviewObservationRecord.workspace_id == workspace_id,
            ReviewObservationRecord.is_current.is_(True),
        )
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review observation not found")
    observation = ReviewObservation(
        external_review_id=review.external_review_id,
        external_location_id=review.external_location_id,
        restaurant_location_id=review.restaurant_location_id,
        rating=review.rating,
        text=review.text,
        language=review.language,
        reviewer_display_name=review.reviewer_display_name,
        provider_response_text=review.provider_response_text,
        provider_response_updated_at=review.provider_response_updated_at,
        review_created_at=review.review_created_at,
        review_updated_at=review.review_updated_at,
        review_state=_validated_review_state(review.review_state),
        observed_at=review.observed_at,
        observation_hash=review.observation_hash,
    )
    analysis = analyze_review(observation)
    try:
        contract = draft_review_response(
            observation,
            analysis,
            review_id=review.id,
            restaurant_name=payload.restaurant_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    current_version = await session.scalar(
        select(ReviewResponseDraftRecord.draft_version)
        .where(
            ReviewResponseDraftRecord.workspace_id == workspace_id,
            ReviewResponseDraftRecord.review_observation_id == review.id,
        )
        .order_by(ReviewResponseDraftRecord.draft_version.desc())
        .limit(1)
    )
    row = ReviewResponseDraftRecord(
        workspace_id=workspace_id,
        review_observation_id=review.id,
        draft_version=(current_version or 0) + 1,
        generated_by_user_id=context.user.id,
        status="draft",
        draft_text=contract.draft_text,
        policy_version=contract.policy_version,
        evidence={"review_hash": contract.evidence_review_hash},
    )
    session.add(row)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="reputation.response_draft_created",
            entity_type="review_response_draft",
            entity_id=row.id,
            payload={
                "review_observation_id": str(review.id),
                "draft_version": row.draft_version,
                "posting_allowed": False,
            },
        )
    )
    await session.commit()
    return ReviewDraftResponse(
        id=row.id,
        review_observation_id=row.review_observation_id,
        status=row.status,
        draft_text=row.draft_text,
        policy_version=row.policy_version,
    )


@router.get(
    "/workspaces/{workspace_id}/review-analyses",
    response_model=list[dict[str, Any]],
)
async def list_review_analyses(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, Any]]:
    _require_enabled()
    await _membership(workspace_id, session, auth_service, context)
    rows = (
        await session.scalars(
            select(ReviewAnalysisRecord)
            .where(ReviewAnalysisRecord.workspace_id == workspace_id)
            .order_by(ReviewAnalysisRecord.created_at.desc(), ReviewAnalysisRecord.id)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "review_observation_id": str(row.review_observation_id),
            "themes": row.themes,
            "praise": row.praise,
            "concerns": row.concerns,
            "risk_level": row.risk_level,
            "escalation_reasons": row.escalation_reasons,
            "fingerprint": row.fingerprint,
        }
        for row in rows
    ]
