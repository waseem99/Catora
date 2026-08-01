from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.local_profiles import (
    BranchLocalProfileLink,
    LocalProfileConflictRecord,
    LocalProfileObservationRecord,
    LocalProfileProviderAccount,
)
from catora_api.local_profiles.evaluator import (
    evaluate_profile_conflicts,
    match_profile_to_locations,
    profile_completeness,
)
from catora_api.local_profiles.models import (
    BranchProfileMatch,
    LocalAddress,
    LocalProfileObservation,
    LocalProviderAccount,
    RestaurantLocationIdentity,
)
from catora_api.local_profiles.provider import LocalProfileProvider


class LocalProfileServiceError(ValueError):
    pass


class LocalProfileIntelligenceService:
    async def create_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        account: LocalProviderAccount,
    ) -> LocalProfileProviderAccount:
        existing = await session.scalar(
            select(LocalProfileProviderAccount).where(
                LocalProfileProviderAccount.workspace_id == workspace_id,
                LocalProfileProviderAccount.provider == account.provider,
                LocalProfileProviderAccount.external_account_id
                == account.external_account_id,
            )
        )
        if existing is not None:
            raise LocalProfileServiceError("Local profile provider account already exists")
        record = LocalProfileProviderAccount(
            workspace_id=workspace_id,
            provider=account.provider,
            external_account_id=account.external_account_id,
            display_name=account.display_name,
            credential_reference=account.credential_reference,
            capabilities={
                capability.operation: capability.model_dump(
                    mode="json",
                    exclude_none=True,
                )
                for capability in account.capabilities
            },
            status="ready",
            sync_checkpoint={},
        )
        session.add(record)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="local_profile.account_connected",
                entity_type="local_profile_provider_account",
                entity_id=record.id,
                payload={
                    "provider": account.provider,
                    "external_account_id_hash": _hash_identifier(
                        account.external_account_id
                    ),
                    "capability_states": {
                        capability.operation: capability.state
                        for capability in account.capabilities
                    },
                },
            )
        )
        await session.commit()
        return record

    async def sync_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        account_id: uuid.UUID,
        provider: LocalProfileProvider,
        locations: tuple[RestaurantLocationIdentity, ...],
    ) -> dict[str, int]:
        account_record = await self._account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            lock=True,
        )
        account = LocalProviderAccount(
            provider=cast("google_business_profile | synthetic", account_record.provider),
            external_account_id=account_record.external_account_id,
            display_name=account_record.display_name,
            credential_reference=account_record.credential_reference,
            capabilities=tuple(
                _capability_from_payload(payload)
                for _, payload in sorted(account_record.capabilities.items())
            ),
        )
        accepted = 0
        duplicate = 0
        exact = 0
        alias = 0
        ambiguous = 0
        unmatched = 0
        conflict_count = 0
        seen_profiles: set[str] = set()
        async for observation in provider.observations(
            account,
            checkpoint={
                str(key): str(value)
                for key, value in account_record.sync_checkpoint.items()
            },
        ):
            seen_profiles.add(observation.external_profile_id)
            completeness = profile_completeness(observation)
            existing = await session.scalar(
                select(LocalProfileObservationRecord).where(
                    LocalProfileObservationRecord.provider_account_id == account_record.id,
                    LocalProfileObservationRecord.external_profile_id
                    == observation.external_profile_id,
                    LocalProfileObservationRecord.observation_hash
                    == observation.observation_hash,
                )
            )
            if existing is not None:
                duplicate += 1
                observation_record = existing
            else:
                await session.execute(
                    update(LocalProfileObservationRecord)
                    .where(
                        LocalProfileObservationRecord.provider_account_id
                        == account_record.id,
                        LocalProfileObservationRecord.external_profile_id
                        == observation.external_profile_id,
                        LocalProfileObservationRecord.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
                observation_record = LocalProfileObservationRecord(
                    workspace_id=workspace_id,
                    provider_account_id=account_record.id,
                    external_profile_id=observation.external_profile_id,
                    provider_location_name=observation.provider_location_name,
                    profile_state=observation.profile_state,
                    title=observation.title,
                    phone=observation.phone,
                    website_url=observation.website_url,
                    menu_url=observation.menu_url,
                    ordering_url=observation.ordering_url,
                    address=observation.address.model_dump(mode="json"),
                    latitude=(
                        str(observation.latitude)
                        if observation.latitude is not None
                        else None
                    ),
                    longitude=(
                        str(observation.longitude)
                        if observation.longitude is not None
                        else None
                    ),
                    regular_hours=[
                        item.model_dump(mode="json")
                        for item in observation.regular_hours
                    ],
                    special_hours=[
                        item.model_dump(mode="json")
                        for item in observation.special_hours
                    ],
                    categories=list(observation.categories),
                    attributes=observation.attributes,
                    service_areas=list(observation.service_areas),
                    media_summary={"count": observation.media_count},
                    completeness=completeness.model_dump(mode="json"),
                    raw_fields_present=list(completeness.present_fields),
                    observed_at=observation.observed_at,
                    source_updated_at=observation.source_updated_at,
                    observation_hash=observation.observation_hash,
                    is_current=True,
                )
                session.add(observation_record)
                await session.flush()
                accepted += 1
            match = match_profile_to_locations(observation, locations)
            if match.state == "exact":
                exact += 1
            elif match.state == "alias":
                alias += 1
            elif match.state == "ambiguous":
                ambiguous += 1
            else:
                unmatched += 1
            link = await self._upsert_link(
                session,
                workspace_id=workspace_id,
                account_id=account_record.id,
                match=match,
            )
            if match.location_id is not None:
                location = next(
                    candidate
                    for candidate in locations
                    if candidate.location_id == match.location_id
                )
                for conflict in evaluate_profile_conflicts(observation, location):
                    await self._upsert_conflict(
                        session,
                        workspace_id=workspace_id,
                        link_id=link.id,
                        observation_id=observation_record.id,
                        conflict=conflict,
                        observed_at=observation.observed_at,
                    )
                    conflict_count += 1
        account_record.last_synced_at = datetime.now(UTC)
        account_record.sync_checkpoint = {
            "last_profile_id": max(seen_profiles) if seen_profiles else None,
            "profile_count": len(seen_profiles),
        }
        summary = {
            "accepted": accepted,
            "duplicate": duplicate,
            "profiles": len(seen_profiles),
            "exact": exact,
            "alias": alias,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
            "conflicts": conflict_count,
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="local_profile.sync_completed",
                entity_type="local_profile_provider_account",
                entity_id=account_record.id,
                payload=summary,
            )
        )
        await session.commit()
        return summary

    async def disconnect_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> LocalProfileProviderAccount:
        account = await self._account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            lock=True,
        )
        account.status = "disconnected"
        account.credential_reference = "revoked"
        account.disconnected_at = datetime.now(UTC)
        await session.execute(
            update(LocalProfileObservationRecord)
            .where(
                LocalProfileObservationRecord.provider_account_id == account.id,
                LocalProfileObservationRecord.is_current.is_(True),
            )
            .values(is_current=False)
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="local_profile.account_disconnected",
                entity_type="local_profile_provider_account",
                entity_id=account.id,
                payload={"provider": account.provider},
            )
        )
        await session.commit()
        return account

    async def _upsert_link(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        match: BranchProfileMatch,
    ) -> BranchLocalProfileLink:
        link = await session.scalar(
            select(BranchLocalProfileLink).where(
                BranchLocalProfileLink.workspace_id == workspace_id,
                BranchLocalProfileLink.provider_account_id == account_id,
                BranchLocalProfileLink.external_profile_id == match.external_profile_id,
            )
        )
        if link is None:
            link = BranchLocalProfileLink(
                workspace_id=workspace_id,
                provider_account_id=account_id,
                external_profile_id=match.external_profile_id,
                restaurant_location_id=match.location_id,
                match_state=match.state,
                match_method=match.method,
                confidence_basis_points=match.confidence_basis_points,
                evidence=match.model_dump(mode="json", exclude_none=True),
            )
            session.add(link)
            await session.flush()
            return link
        if link.decided_at is None:
            link.restaurant_location_id = match.location_id
            link.match_state = match.state
            link.match_method = match.method
            link.confidence_basis_points = match.confidence_basis_points
            link.evidence = match.model_dump(mode="json", exclude_none=True)
        return link

    async def _upsert_conflict(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        link_id: uuid.UUID,
        observation_id: uuid.UUID,
        conflict: object,
        observed_at: datetime,
    ) -> LocalProfileConflictRecord:
        from catora_api.local_profiles.models import LocalProfileConflict

        value = cast(LocalProfileConflict, conflict)
        record = await session.scalar(
            select(LocalProfileConflictRecord).where(
                LocalProfileConflictRecord.workspace_id == workspace_id,
                LocalProfileConflictRecord.branch_profile_link_id == link_id,
                LocalProfileConflictRecord.field_key == value.field_key,
                LocalProfileConflictRecord.fingerprint == value.fingerprint,
            )
        )
        if record is None:
            record = LocalProfileConflictRecord(
                workspace_id=workspace_id,
                branch_profile_link_id=link_id,
                local_profile_observation_id=observation_id,
                field_key=value.field_key,
                severity=value.severity,
                status="open",
                restaurant_value=value.restaurant_value,
                provider_value=value.provider_value,
                evidence={"fingerprint": value.fingerprint},
                fingerprint=value.fingerprint,
                explanation=value.explanation,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            session.add(record)
        else:
            record.local_profile_observation_id = observation_id
            record.last_seen_at = observed_at
            record.status = "open"
            record.resolved_at = None
        return record

    async def _account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        lock: bool = False,
    ) -> LocalProfileProviderAccount:
        statement = select(LocalProfileProviderAccount).where(
            LocalProfileProviderAccount.id == account_id,
            LocalProfileProviderAccount.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        account = await session.scalar(statement)
        if account is None:
            raise LocalProfileServiceError("Local profile account not found")
        if account.status != "ready":
            raise LocalProfileServiceError("Local profile account is not active")
        return account


def _capability_from_payload(payload: object):
    from catora_api.local_profiles.models import ProviderCapability

    return ProviderCapability.model_validate(payload)


def _hash_identifier(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()
