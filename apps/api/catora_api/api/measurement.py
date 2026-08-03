from __future__ import annotations

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
from catora_api.config import get_settings
from catora_api.db.models.measurement import (
    MeasurementObservationRecord,
    MeasurementProviderAccount,
)
from catora_api.measurement.models import (
    ChangeAnnotation,
    MeasurementAttribution,
    MeasurementObservation,
    MeasurementProperty,
    MeasurementProviderCapability,
)
from catora_api.measurement.provider import SyntheticMeasurementProvider
from catora_api.measurement.service import MeasurementService, MeasurementServiceError

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/measurements",
    tags=["aggregate measurement"],
)


class MeasurementApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticMeasurementImportRequest(MeasurementApiModel):
    external_account_id: str = Field(min_length=1, max_length=500)
    properties: tuple[MeasurementProperty, ...] = Field(min_length=1, max_length=100)
    observations: tuple[MeasurementObservation, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    idempotency_key: str = Field(min_length=8, max_length=160)


class SyntheticMeasurementImportResponse(MeasurementApiModel):
    account_id: uuid.UUID
    properties: int
    accepted: int
    duplicate: int


class MeasurementAccountResponse(MeasurementApiModel):
    id: uuid.UUID
    provider: str
    external_account_id: str
    capabilities: dict[str, Any]
    status: str
    sync_checkpoint: dict[str, Any]
    disconnected_at: str | None


class MeasurementObservationResponse(MeasurementApiModel):
    id: uuid.UUID
    measurement_property_id: uuid.UUID
    provider: str
    metric_key: str
    metric_version: str
    value_microunits: int
    dimensions: dict[str, str]
    window_start: str
    window_end: str
    timezone: str
    sample_state: str
    freshness_state: str
    source_definition: dict[str, Any]
    observed_at: str
    observation_hash: str


class MeasurementAttributionRequest(MeasurementApiModel):
    attribution: MeasurementAttribution


class MeasurementAttributionResponse(MeasurementApiModel):
    id: uuid.UUID
    observation_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    state: str
    method: str
    confidence_basis_points: int
    evidence: dict[str, Any]


class MeasurementAnnotationRequest(MeasurementApiModel):
    annotation: ChangeAnnotation


class MeasurementAnnotationResponse(MeasurementApiModel):
    id: uuid.UUID
    annotation_type: str
    target_type: str
    target_id: uuid.UUID
    occurred_at: str
    source_revision: str | None
    details: dict[str, Any]


def _require_enabled() -> None:
    if not get_settings().measurement_connectors_enabled:
        raise HTTPException(status_code=503, detail="Measurement connectors are disabled")


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


def _require_runner(role: str) -> None:
    if not can(Role(role), "analysis.run"):
        raise AuthorizationError("Measurement import permission required")


def _require_writer(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Measurement annotation permission required")


def _account_response(account: MeasurementProviderAccount) -> MeasurementAccountResponse:
    return MeasurementAccountResponse(
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
    response_model=SyntheticMeasurementImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_synthetic_measurements(
    workspace_id: uuid.UUID,
    payload: SyntheticMeasurementImportRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> SyntheticMeasurementImportResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_runner(role)
    tested_at = max(item.observed_at for item in payload.observations)
    capabilities = (
        MeasurementProviderCapability(
            operation="properties.read",
            state="tested",
            scope="synthetic aggregate fixture",
            tested_at=tested_at,
        ),
        MeasurementProviderCapability(
            operation="observations.read",
            state="tested",
            scope="synthetic aggregate fixture",
            tested_at=tested_at,
        ),
    )
    service = MeasurementService()
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
            provider=SyntheticMeasurementProvider(
                properties=payload.properties,
                items=payload.observations,
            ),
        )
    except MeasurementServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SyntheticMeasurementImportResponse(
        account_id=account.id,
        properties=summary["properties"],
        accepted=summary["accepted"],
        duplicate=summary["duplicate"],
    )


@router.get("/accounts", response_model=list[MeasurementAccountResponse])
async def list_measurement_accounts(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[MeasurementAccountResponse]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(MeasurementProviderAccount)
            .where(MeasurementProviderAccount.workspace_id == workspace_id)
            .order_by(
                MeasurementProviderAccount.provider,
                MeasurementProviderAccount.external_account_id,
                MeasurementProviderAccount.id,
            )
        )
    ).all()
    return [_account_response(row) for row in rows]


@router.get("/observations", response_model=list[MeasurementObservationResponse])
async def list_measurement_observations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[MeasurementObservationResponse]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(MeasurementObservationRecord)
            .where(MeasurementObservationRecord.workspace_id == workspace_id)
            .order_by(
                MeasurementObservationRecord.window_start.desc(),
                MeasurementObservationRecord.metric_key,
                MeasurementObservationRecord.id,
            )
        )
    ).all()
    return [
        MeasurementObservationResponse(
            id=row.id,
            measurement_property_id=row.measurement_property_id,
            provider=row.provider,
            metric_key=row.metric_key,
            metric_version=row.metric_version,
            value_microunits=row.value_microunits,
            dimensions=row.dimensions,
            window_start=row.window_start.isoformat(),
            window_end=row.window_end.isoformat(),
            timezone=row.timezone,
            sample_state=row.sample_state,
            freshness_state=row.freshness_state,
            source_definition=row.source_definition,
            observed_at=row.observed_at.isoformat(),
            observation_hash=row.observation_hash,
        )
        for row in rows
    ]


@router.post(
    "/attributions",
    response_model=MeasurementAttributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_measurement_attribution(
    workspace_id: uuid.UUID,
    payload: MeasurementAttributionRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> MeasurementAttributionResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await MeasurementService().create_attribution(
            session,
            workspace_id=workspace_id,
            attribution=payload.attribution,
        )
    except MeasurementServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MeasurementAttributionResponse(
        id=row.id,
        observation_id=row.measurement_observation_id,
        target_type=row.target_type,
        target_id=row.target_id,
        state=row.attribution_state,
        method=row.method,
        confidence_basis_points=row.confidence_basis_points,
        evidence=row.evidence,
    )


@router.post(
    "/annotations",
    response_model=MeasurementAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_measurement_annotation(
    workspace_id: uuid.UUID,
    payload: MeasurementAnnotationRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> MeasurementAnnotationResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    row = await MeasurementService().create_annotation(
        session,
        workspace_id=workspace_id,
        actor_user_id=context.user.id,
        annotation=payload.annotation,
    )
    return MeasurementAnnotationResponse(
        id=row.id,
        annotation_type=row.annotation_type,
        target_type=row.target_type,
        target_id=row.target_id,
        occurred_at=row.occurred_at.isoformat(),
        source_revision=row.source_revision,
        details=row.details,
    )


@router.delete(
    "/accounts/{account_id}",
    response_model=MeasurementAccountResponse,
)
async def disconnect_measurement_account(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> MeasurementAccountResponse:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_runner(role)
    try:
        account = await MeasurementService().disconnect_account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            actor_user_id=context.user.id,
        )
    except MeasurementServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_response(account)
