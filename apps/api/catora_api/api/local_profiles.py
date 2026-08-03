from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

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
from catora_api.db.models import AuditEvent, Membership
from catora_api.db.models.local_profiles import (
    BranchLocalProfileLink,
    LocalProfileConflictRecord,
    LocalProfileObservationRecord,
    LocalProfileProviderAccount,
)
from catora_api.db.models.restaurant import RestaurantLocation
from catora_api.local_profiles import (
    LocalAddress,
    LocalProfileIntelligenceService,
    LocalProfileObservation,
    LocalProfileServiceError,
    LocalProvider,
    LocalProviderAccount,
    ProviderCapability,
    RestaurantLocationIdentity,
    SyntheticLocalProfileProvider,
)

router = APIRouter(prefix="/api/v1", tags=["local profile intelligence"])


class LocalProfileApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalAccountCreateRequest(LocalProfileApiModel):
    provider: LocalProvider
    external_account_id: str = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, max_length=500)
    credential_reference: str = Field(min_length=1, max_length=500)
    capabilities: tuple[ProviderCapability, ...] = Field(min_length=1, max_length=200)


class LocalAccountResponse(LocalProfileApiModel):
    id: uuid.UUID
    provider: str
    external_account_id: str
    display_name: str | None
    capabilities: dict[str, Any]
    status: str
    last_synced_at: str | None
    sync_checkpoint: dict[str, Any]


class SyntheticLocalSyncRequest(LocalProfileApiModel):
    observations: tuple[LocalProfileObservation, ...] = Field(max_length=5_000)


class LocalSyncResponse(LocalProfileApiModel):
    account_id: uuid.UUID
    summary: dict[str, int]


class LocalObservationResponse(LocalProfileApiModel):
    id: uuid.UUID
    external_profile_id: str
    profile_state: str
    title: str
    phone: str | None
    website_url: str | None
    menu_url: str | None
    ordering_url: str | None
    address: dict[str, Any]
    categories: list[str]
    attributes: dict[str, Any]
    service_areas: list[dict[str, Any]]
    completeness: dict[str, Any]
    observed_at: str
    source_updated_at: str | None
    observation_hash: str
    is_current: bool


class BranchProfileLinkResponse(LocalProfileApiModel):
    id: uuid.UUID
    restaurant_location_id: uuid.UUID | None
    external_profile_id: str
    match_state: str
    match_method: str
    confidence_basis_points: int
    evidence: dict[str, Any]
    decided_by_user_id: uuid.UUID | None
    decided_at: str | None


class ManualProfileLinkRequest(LocalProfileApiModel):
    restaurant_location_id: uuid.UUID


class LocalConflictResponse(LocalProfileApiModel):
    id: uuid.UUID
    branch_profile_link_id: uuid.UUID
    field_key: str
    severity: str
    status: str
    restaurant_value: Any
    provider_value: Any
    evidence: dict[str, Any]
    fingerprint: str
    explanation: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: str | None


async def _membership(
    *,
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> Membership:
    return await auth_service.membership(session, context.user.id, workspace_id)


def _require_source_admin(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Local profile source management permission required")


def _require_owner_or_admin(role: str) -> None:
    if Role(role) not in {Role.OWNER, Role.ADMIN}:
        raise AuthorizationError("Owner or admin permission required")


def _require_feature_enabled() -> None:
    if not get_settings().local_profile_intelligence_enabled:
        raise HTTPException(status_code=503, detail="Local profile intelligence is disabled")


def _account_response(account: LocalProfileProviderAccount) -> LocalAccountResponse:
    return LocalAccountResponse(
        id=account.id,
        provider=account.provider,
        external_account_id=account.external_account_id,
        display_name=account.display_name,
        capabilities=account.capabilities,
        status=account.status,
        last_synced_at=(
            account.last_synced_at.isoformat() if account.last_synced_at is not None else None
        ),
        sync_checkpoint=account.sync_checkpoint,
    )


def _link_response(link: BranchLocalProfileLink) -> BranchProfileLinkResponse:
    return BranchProfileLinkResponse(
        id=link.id,
        restaurant_location_id=link.restaurant_location_id,
        external_profile_id=link.external_profile_id,
        match_state=link.match_state,
        match_method=link.match_method,
        confidence_basis_points=link.confidence_basis_points,
        evidence=link.evidence,
        decided_by_user_id=link.decided_by_user_id,
        decided_at=link.decided_at.isoformat() if link.decided_at is not None else None,
    )


@router.post(
    "/workspaces/{workspace_id}/local-profile-accounts",
    response_model=LocalAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_local_profile_account(
    workspace_id: uuid.UUID,
    payload: LocalAccountCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> LocalAccountResponse:
    _require_feature_enabled()
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_admin(membership.role)
    try:
        account_contract = LocalProviderAccount(
            provider=payload.provider,
            external_account_id=payload.external_account_id,
            display_name=payload.display_name,
            credential_reference=payload.credential_reference,
            capabilities=payload.capabilities,
        )
        account = await LocalProfileIntelligenceService().create_account(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            account=account_contract,
        )
    except (ValueError, LocalProfileServiceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_response(account)


@router.get(
    "/workspaces/{workspace_id}/local-profile-accounts",
    response_model=list[LocalAccountResponse],
)
async def list_local_profile_accounts(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[LocalAccountResponse]:
    _require_feature_enabled()
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(LocalProfileProviderAccount)
            .where(LocalProfileProviderAccount.workspace_id == workspace_id)
            .order_by(
                LocalProfileProviderAccount.provider,
                LocalProfileProviderAccount.external_account_id,
                LocalProfileProviderAccount.id,
            )
        )
    ).all()
    return [_account_response(row) for row in rows]


@router.post(
    "/workspaces/{workspace_id}/local-profile-accounts/{account_id}/sync-synthetic",
    response_model=LocalSyncResponse,
)
async def sync_synthetic_local_profiles(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: SyntheticLocalSyncRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> LocalSyncResponse:
    _require_feature_enabled()
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_admin(membership.role)
    account = await session.scalar(
        select(LocalProfileProviderAccount).where(
            LocalProfileProviderAccount.id == account_id,
            LocalProfileProviderAccount.workspace_id == workspace_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Local profile account not found")
    if account.provider != "synthetic":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only the synthetic provider is accepted in this runtime. "
                "Google Business Profile requires account-level acceptance."
            ),
        )
    locations = await _restaurant_location_identities(session, workspace_id=workspace_id)
    try:
        summary = await LocalProfileIntelligenceService().sync_account(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            account_id=account_id,
            provider=SyntheticLocalProfileProvider(payload.observations),
            locations=locations,
        )
    except LocalProfileServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LocalSyncResponse(account_id=account_id, summary=summary)


@router.get(
    "/workspaces/{workspace_id}/local-profile-observations",
    response_model=list[LocalObservationResponse],
)
async def list_local_profile_observations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[LocalObservationResponse]:
    _require_feature_enabled()
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(LocalProfileObservationRecord)
            .where(
                LocalProfileObservationRecord.workspace_id == workspace_id,
                LocalProfileObservationRecord.is_current.is_(True),
            )
            .order_by(
                LocalProfileObservationRecord.external_profile_id,
                LocalProfileObservationRecord.observed_at.desc(),
            )
        )
    ).all()
    return [
        LocalObservationResponse(
            id=row.id,
            external_profile_id=row.external_profile_id,
            profile_state=row.profile_state,
            title=row.title,
            phone=row.phone,
            website_url=row.website_url,
            menu_url=row.menu_url,
            ordering_url=row.ordering_url,
            address=row.address,
            categories=row.categories,
            attributes=row.attributes,
            service_areas=row.service_areas,
            completeness=row.completeness,
            observed_at=row.observed_at.isoformat(),
            source_updated_at=(
                row.source_updated_at.isoformat()
                if row.source_updated_at is not None
                else None
            ),
            observation_hash=row.observation_hash,
            is_current=row.is_current,
        )
        for row in rows
    ]


@router.get(
    "/workspaces/{workspace_id}/local-profile-links",
    response_model=list[BranchProfileLinkResponse],
)
async def list_local_profile_links(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[BranchProfileLinkResponse]:
    _require_feature_enabled()
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(BranchLocalProfileLink)
            .where(BranchLocalProfileLink.workspace_id == workspace_id)
            .order_by(
                BranchLocalProfileLink.match_state,
                BranchLocalProfileLink.external_profile_id,
            )
        )
    ).all()
    return [_link_response(row) for row in rows]


@router.put(
    "/workspaces/{workspace_id}/local-profile-links/{link_id}",
    response_model=BranchProfileLinkResponse,
)
async def decide_local_profile_link(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: ManualProfileLinkRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> BranchProfileLinkResponse:
    _require_feature_enabled()
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_owner_or_admin(membership.role)
    location = await session.scalar(
        select(RestaurantLocation).where(
            RestaurantLocation.id == payload.restaurant_location_id,
            RestaurantLocation.workspace_id == workspace_id,
        )
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Restaurant location not found")
    link = await session.scalar(
        select(BranchLocalProfileLink)
        .where(
            BranchLocalProfileLink.id == link_id,
            BranchLocalProfileLink.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Local profile link not found")
    previous_state = link.match_state
    previous_location_id = link.restaurant_location_id
    link.restaurant_location_id = location.id
    link.match_state = "exact"
    link.match_method = "human_decision"
    link.confidence_basis_points = 10_000
    link.decided_by_user_id = context.user.id
    link.decided_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="local_profile.link_decided",
            entity_type="branch_local_profile_link",
            entity_id=link.id,
            payload={
                "previous_state": previous_state,
                "previous_location_id": (
                    str(previous_location_id) if previous_location_id is not None else None
                ),
                "restaurant_location_id": str(location.id),
            },
        )
    )
    await session.commit()
    return _link_response(link)


@router.get(
    "/workspaces/{workspace_id}/local-profile-conflicts",
    response_model=list[LocalConflictResponse],
)
async def list_local_profile_conflicts(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[LocalConflictResponse]:
    _require_feature_enabled()
    await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(LocalProfileConflictRecord)
            .where(LocalProfileConflictRecord.workspace_id == workspace_id)
            .order_by(
                LocalProfileConflictRecord.status,
                LocalProfileConflictRecord.severity,
                LocalProfileConflictRecord.field_key,
                LocalProfileConflictRecord.id,
            )
        )
    ).all()
    return [
        LocalConflictResponse(
            id=row.id,
            branch_profile_link_id=row.branch_profile_link_id,
            field_key=row.field_key,
            severity=row.severity,
            status=row.status,
            restaurant_value=row.restaurant_value,
            provider_value=row.provider_value,
            evidence=row.evidence,
            fingerprint=row.fingerprint,
            explanation=row.explanation,
            first_seen_at=row.first_seen_at.isoformat(),
            last_seen_at=row.last_seen_at.isoformat(),
            resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        )
        for row in rows
    ]


@router.delete(
    "/workspaces/{workspace_id}/local-profile-accounts/{account_id}",
    response_model=LocalAccountResponse,
)
async def disconnect_local_profile_account(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> LocalAccountResponse:
    _require_feature_enabled()
    membership = await _membership(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_source_admin(membership.role)
    try:
        account = await LocalProfileIntelligenceService().disconnect_account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            actor_user_id=context.user.id,
        )
    except LocalProfileServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_response(account)


async def _restaurant_location_identities(
    session: SessionDependency,
    *,
    workspace_id: uuid.UUID,
) -> tuple[RestaurantLocationIdentity, ...]:
    rows = (
        await session.scalars(
            select(RestaurantLocation)
            .where(
                RestaurantLocation.workspace_id == workspace_id,
                RestaurantLocation.status == "active",
            )
            .order_by(RestaurantLocation.canonical_key, RestaurantLocation.id)
        )
    ).all()
    identities: list[RestaurantLocationIdentity] = []
    for row in rows:
        address_payload = cast(dict[str, Any], row.address or {})
        address_lines_value = address_payload.get("address_lines")
        address_lines = (
            tuple(value for value in address_lines_value if isinstance(value, str))
            if isinstance(address_lines_value, list)
            else ()
        )
        street_address = _optional_string(address_payload.get("street_address"))
        if street_address is not None:
            address_lines = (street_address, *address_lines)
        identities.append(
            RestaurantLocationIdentity(
                location_id=row.id,
                canonical_key=row.canonical_key,
                external_location_id=row.external_location_id,
                name=row.name,
                aliases=(),
                phone=row.phone,
                address=LocalAddress(
                    address_lines=address_lines,
                    locality=_optional_string(
                        address_payload.get("address_locality")
                        or address_payload.get("locality")
                    ),
                    administrative_area=_optional_string(
                        address_payload.get("address_region")
                        or address_payload.get("administrative_area")
                    ),
                    postal_code=_optional_string(address_payload.get("postal_code")),
                    country_code=_country_code(
                        address_payload.get("address_country")
                        or address_payload.get("country_code")
                    ),
                ),
                website_url=row.website_url,
            )
        )
    return tuple(identities)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _country_code(value: object) -> str | None:
    result = _optional_string(value)
    return result.upper() if result is not None and len(result) == 2 else None
