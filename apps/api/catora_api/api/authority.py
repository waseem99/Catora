from __future__ import annotations

import uuid
from datetime import datetime
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
from catora_api.authority.models import (
    AuthorityCapability,
    AuthorityObservation,
    OutreachChannel,
    OutreachDecision,
    OutreachDraft,
    SuppressionReason,
    SuppressionRecord,
)
from catora_api.authority.provider import SyntheticAuthorityProvider
from catora_api.authority.service import AuthorityService, AuthorityServiceError
from catora_api.config import get_settings
from catora_api.db.models.authority import (
    AuthorityObservationRecord,
    AuthorityOpportunityRecord,
    AuthorityProviderAccount,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/authority",
    tags=["off-page authority"],
)


class AuthorityApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticAuthorityImportRequest(AuthorityApiModel):
    external_account_id: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)
    observations: tuple[AuthorityObservation, ...] = Field(min_length=1, max_length=5_000)


class SyntheticAuthorityImportResponse(AuthorityApiModel):
    account_id: uuid.UUID
    accepted: int
    duplicate: int
    prohibited: int
    opportunities: int


class AuthorityAccountResponse(AuthorityApiModel):
    id: uuid.UUID
    provider: str
    external_account_id: str
    capabilities: dict[str, Any]
    status: str
    sync_checkpoint: dict[str, Any]
    disconnected_at: str | None


class AuthorityObservationResponse(AuthorityApiModel):
    id: uuid.UUID
    observation_type: str
    source_url: str
    target_url: str
    identity_state: str
    link_state: str
    provider_metrics: dict[str, Any]
    observed_at: str
    observation_hash: str


class AuthorityOpportunityResponse(AuthorityApiModel):
    id: uuid.UUID
    opportunity_type: str
    state: str
    risk_state: str
    title: str
    rationale: str
    verification_method: str
    owner_role: str
    score_basis_points: int
    evidence_hashes: list[str]


class SuppressionRequest(AuthorityApiModel):
    normalized_target: str = Field(min_length=1, max_length=500)
    reason: SuppressionReason
    effective_at: datetime
    expires_at: datetime | None = None


class OutreachDraftRequest(AuthorityApiModel):
    normalized_target: str = Field(min_length=1, max_length=500)
    channel: OutreachChannel
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5_000)
    factual_claims: tuple[str, ...] = Field(default=(), max_length=20)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=50)
    suppression_checked: bool
    legal_basis_confirmed: bool


class OutreachDraftResponse(AuthorityApiModel):
    id: uuid.UUID
    status: str
    draft_version: int
    send_allowed: bool = False


class OutreachDecisionRequest(AuthorityApiModel):
    decision: OutreachDecision
    reason: str = Field(min_length=1, max_length=2_000)


class OutreachDecisionResponse(AuthorityApiModel):
    id: uuid.UUID
    decision: str
    send_allowed: bool = False


def _require_enabled() -> None:
    if not get_settings().authority_intelligence_enabled:
        raise HTTPException(status_code=503, detail="Authority intelligence is disabled")


async def _role(
    *,
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> str:
    membership = await auth_service.membership(
        session,
        context.user.id,
        workspace_id,
    )
    return membership.role


def _require_writer(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Authority workflow permission required")


def _account_response(account: AuthorityProviderAccount) -> AuthorityAccountResponse:
    return AuthorityAccountResponse(
        id=account.id,
        provider=account.provider,
        external_account_id=account.external_account_id,
        capabilities=account.capabilities,
        status=account.status,
        sync_checkpoint=account.sync_checkpoint,
        disconnected_at=(
            account.disconnected_at.isoformat()
            if account.disconnected_at is not None
            else None
        ),
    )


@router.post(
    "/import-synthetic",
    response_model=SyntheticAuthorityImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_synthetic_authority(
    workspace_id: uuid.UUID,
    payload: SyntheticAuthorityImportRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> SyntheticAuthorityImportResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    service = AuthorityService()
    capabilities = (
        AuthorityCapability(
            operation="observations.read",
            state="tested",
            scope="synthetic authority fixture",
            tested_at=max(item.observed_at for item in payload.observations),
        ),
    )
    try:
        account = await service.create_account(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            provider="synthetic",
            external_account_id=(
                f"{payload.external_account_id}:{payload.idempotency_key}"
            ),
            credential_reference="synthetic:none",
            capabilities=capabilities,
        )
        summary = await service.sync_account(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            account_id=account.id,
            provider=SyntheticAuthorityProvider(items=payload.observations),
        )
    except AuthorityServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SyntheticAuthorityImportResponse(
        account_id=account.id,
        accepted=summary["accepted"],
        duplicate=summary["duplicate"],
        prohibited=summary["prohibited"],
        opportunities=summary["opportunities"],
    )


@router.get("/accounts", response_model=list[AuthorityAccountResponse])
async def list_authority_accounts(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[AuthorityAccountResponse]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(AuthorityProviderAccount)
            .where(AuthorityProviderAccount.workspace_id == workspace_id)
            .order_by(
                AuthorityProviderAccount.provider,
                AuthorityProviderAccount.external_account_id,
                AuthorityProviderAccount.id,
            )
        )
    ).all()
    return [_account_response(row) for row in rows]


@router.get("/observations", response_model=list[AuthorityObservationResponse])
async def list_authority_observations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[AuthorityObservationResponse]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(AuthorityObservationRecord)
            .where(AuthorityObservationRecord.workspace_id == workspace_id)
            .order_by(
                AuthorityObservationRecord.observed_at.desc(),
                AuthorityObservationRecord.id,
            )
        )
    ).all()
    return [
        AuthorityObservationResponse(
            id=row.id,
            observation_type=row.observation_type,
            source_url=row.source_url,
            target_url=row.target_url,
            identity_state=row.identity_state,
            link_state=row.link_state,
            provider_metrics=row.provider_metrics,
            observed_at=row.observed_at.isoformat(),
            observation_hash=row.observation_hash,
        )
        for row in rows
    ]


@router.get("/opportunities", response_model=list[AuthorityOpportunityResponse])
async def list_authority_opportunities(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[AuthorityOpportunityResponse]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(AuthorityOpportunityRecord)
            .where(AuthorityOpportunityRecord.workspace_id == workspace_id)
            .order_by(
                AuthorityOpportunityRecord.score_basis_points.desc(),
                AuthorityOpportunityRecord.created_at.desc(),
            )
        )
    ).all()
    return [
        AuthorityOpportunityResponse(
            id=row.id,
            opportunity_type=row.opportunity_type,
            state=row.state,
            risk_state=row.risk_state,
            title=row.title,
            rationale=row.rationale,
            verification_method=row.verification_method,
            owner_role=row.owner_role,
            score_basis_points=row.score_basis_points,
            evidence_hashes=row.evidence_hashes,
        )
        for row in rows
    ]


@router.post("/suppressions", status_code=status.HTTP_201_CREATED)
async def create_authority_suppression(
    workspace_id: uuid.UUID,
    payload: SuppressionRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, str]:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await AuthorityService().create_suppression(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            suppression=SuppressionRecord(
                normalized_target=payload.normalized_target,
                reason=payload.reason,
                effective_at=payload.effective_at,
                expires_at=payload.expires_at,
            ),
        )
    except (AuthorityServiceError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": str(row.id), "status": "suppressed"}


@router.post(
    "/opportunities/{opportunity_id}/outreach-drafts",
    response_model=OutreachDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_authority_outreach_draft(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: OutreachDraftRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> OutreachDraftResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await AuthorityService().create_outreach_draft(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            normalized_target=payload.normalized_target,
            draft=OutreachDraft(
                opportunity_id=opportunity_id,
                channel=payload.channel,
                subject=payload.subject,
                body=payload.body,
                factual_claims=payload.factual_claims,
                evidence_hashes=payload.evidence_hashes,
                suppression_checked=payload.suppression_checked,
                legal_basis_confirmed=payload.legal_basis_confirmed,
            ),
        )
    except (AuthorityServiceError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OutreachDraftResponse(
        id=row.id,
        status=row.status,
        draft_version=row.draft_version,
    )


@router.post(
    "/outreach-drafts/{draft_id}/decision",
    response_model=OutreachDecisionResponse,
)
async def decide_authority_outreach_draft(
    workspace_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: OutreachDecisionRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> OutreachDecisionResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await AuthorityService().decide_outreach_draft(
            session,
            workspace_id=workspace_id,
            draft_id=draft_id,
            actor_user_id=context.user.id,
            decision=payload.decision,
            reason=payload.reason,
        )
    except AuthorityServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OutreachDecisionResponse(id=row.id, decision=row.decision)


@router.delete(
    "/accounts/{account_id}",
    response_model=AuthorityAccountResponse,
)
async def disconnect_authority_account(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> AuthorityAccountResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        account = await AuthorityService().disconnect_account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            actor_user_id=context.user.id,
        )
    except AuthorityServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_response(account)
