from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.measurement import (
    MeasurementAttributionLink,
    MeasurementChangeAnnotation,
    MeasurementObservationRecord,
    MeasurementPropertyRecord,
    MeasurementProviderAccount,
)
from catora_api.measurement.evaluator import dimension_hash
from catora_api.measurement.models import (
    ChangeAnnotation,
    MeasurementAttribution,
    MeasurementObservation,
    MeasurementProperty,
    MeasurementProvider,
    MeasurementProviderCapability,
)
from catora_api.measurement.provider import MeasurementSourceProvider

_MANAGED_CREDENTIAL_PREFIXES = ("env:", "vault:", "secret:", "synthetic:")


class MeasurementServiceError(ValueError):
    pass


class MeasurementService:
    async def create_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        provider: MeasurementProvider,
        external_account_id: str,
        credential_reference: str,
        capabilities: tuple[MeasurementProviderCapability, ...],
    ) -> MeasurementProviderAccount:
        self._validate_account_contract(
            provider=provider,
            credential_reference=credential_reference,
            capabilities=capabilities,
        )
        capability_payload = {
            item.operation: item.model_dump(mode="json", exclude_none=True)
            for item in capabilities
        }
        existing = await session.scalar(
            select(MeasurementProviderAccount).where(
                MeasurementProviderAccount.workspace_id == workspace_id,
                MeasurementProviderAccount.provider == provider,
                MeasurementProviderAccount.external_account_id == external_account_id,
            )
        )
        if existing is not None:
            if (
                provider == "synthetic"
                and existing.status == "ready"
                and existing.credential_reference == credential_reference
                and existing.capabilities == capability_payload
            ):
                return existing
            raise MeasurementServiceError(
                "Measurement provider account already exists with different configuration"
            )
        account = MeasurementProviderAccount(
            workspace_id=workspace_id,
            provider=provider,
            external_account_id=external_account_id,
            credential_reference=credential_reference,
            capabilities=capability_payload,
            status="ready",
            sync_checkpoint={},
        )
        session.add(account)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="measurement.account_connected",
                entity_type="measurement_provider_account",
                entity_id=account.id,
                payload={
                    "provider": provider,
                    "external_account_id_hash": hashlib.sha256(
                        external_account_id.encode("utf-8")
                    ).hexdigest(),
                    "capability_states": {
                        item.operation: item.state for item in capabilities
                    },
                },
            )
        )
        await session.commit()
        return account

    async def sync_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        account_id: uuid.UUID,
        provider: MeasurementSourceProvider,
    ) -> dict[str, int]:
        account = await self._account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            lock=True,
        )
        properties = await provider.discover_properties()
        accepted = 0
        duplicate = 0
        property_count = 0
        for property_contract in properties:
            if property_contract.provider != account.provider:
                raise MeasurementServiceError(
                    "Measurement property provider does not match its account"
                )
            property_row = await self._upsert_property(
                session,
                workspace_id=workspace_id,
                account=account,
                property_contract=property_contract,
            )
            property_count += 1
            async for observation in provider.observations(
                property_contract,
                checkpoint={
                    str(key): str(value)
                    for key, value in account.sync_checkpoint.items()
                },
            ):
                if observation.provider != account.provider:
                    raise MeasurementServiceError(
                        "Measurement observation provider does not match its account"
                    )
                if (
                    observation.external_property_id
                    != property_contract.external_property_id
                ):
                    raise MeasurementServiceError(
                        "Measurement observation property does not match its batch"
                    )
                created = await self._store_observation(
                    session,
                    workspace_id=workspace_id,
                    property_row=property_row,
                    observation=observation,
                )
                if created:
                    accepted += 1
                else:
                    duplicate += 1
        account.sync_checkpoint = {
            "last_synced_at": datetime.now(UTC).isoformat(),
            "property_count": property_count,
            "accepted_observations": accepted,
            "duplicate_observations": duplicate,
        }
        summary = {
            "properties": property_count,
            "accepted": accepted,
            "duplicate": duplicate,
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="measurement.sync_completed",
                entity_type="measurement_provider_account",
                entity_id=account.id,
                payload=summary,
            )
        )
        await session.commit()
        return summary

    async def create_attribution(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        attribution: MeasurementAttribution,
    ) -> MeasurementAttributionLink:
        observation = await session.scalar(
            select(MeasurementObservationRecord).where(
                MeasurementObservationRecord.id == attribution.observation_id,
                MeasurementObservationRecord.workspace_id == workspace_id,
            )
        )
        if observation is None:
            raise MeasurementServiceError("Measurement observation not found")
        existing = await session.scalar(
            select(MeasurementAttributionLink).where(
                MeasurementAttributionLink.workspace_id == workspace_id,
                MeasurementAttributionLink.measurement_observation_id
                == attribution.observation_id,
                MeasurementAttributionLink.target_type == attribution.target_type,
                MeasurementAttributionLink.target_id == attribution.target_id,
            )
        )
        if existing is not None:
            return existing
        row = MeasurementAttributionLink(
            workspace_id=workspace_id,
            measurement_observation_id=attribution.observation_id,
            target_type=attribution.target_type,
            target_id=attribution.target_id,
            attribution_state=attribution.state,
            method=attribution.method,
            confidence_basis_points=attribution.confidence_basis_points,
            evidence=attribution.evidence,
        )
        session.add(row)
        await session.commit()
        return row

    async def create_annotation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        annotation: ChangeAnnotation,
    ) -> MeasurementChangeAnnotation:
        row = MeasurementChangeAnnotation(
            workspace_id=workspace_id,
            annotation_type=annotation.annotation_type,
            target_type=annotation.target_type,
            target_id=annotation.target_id,
            occurred_at=annotation.occurred_at,
            source_revision=annotation.source_revision,
            details=annotation.details,
            created_by_user_id=actor_user_id,
        )
        session.add(row)
        await session.commit()
        return row

    async def disconnect_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> MeasurementProviderAccount:
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
            update(MeasurementPropertyRecord)
            .where(
                MeasurementPropertyRecord.provider_account_id == account.id,
                MeasurementPropertyRecord.status == "ready",
            )
            .values(status="disconnected")
        )
        await session.execute(
            update(MeasurementObservationRecord)
            .where(
                MeasurementObservationRecord.measurement_property_id.in_(
                    select(MeasurementPropertyRecord.id).where(
                        MeasurementPropertyRecord.provider_account_id == account.id
                    )
                ),
                MeasurementObservationRecord.freshness_state == "current",
            )
            .values(freshness_state="disconnected")
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="measurement.account_disconnected",
                entity_type="measurement_provider_account",
                entity_id=account.id,
                payload={"provider": account.provider},
            )
        )
        await session.commit()
        return account

    async def _upsert_property(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account: MeasurementProviderAccount,
        property_contract: MeasurementProperty,
    ) -> MeasurementPropertyRecord:
        row = await session.scalar(
            select(MeasurementPropertyRecord).where(
                MeasurementPropertyRecord.workspace_id == workspace_id,
                MeasurementPropertyRecord.provider_account_id == account.id,
                MeasurementPropertyRecord.external_property_id
                == property_contract.external_property_id,
            )
        )
        metadata = property_contract.model_dump(mode="json", exclude_none=True)
        if row is None:
            row = MeasurementPropertyRecord(
                workspace_id=workspace_id,
                provider_account_id=account.id,
                external_property_id=property_contract.external_property_id,
                property_type=property_contract.property_type,
                display_name=property_contract.display_name,
                canonical_origin=property_contract.canonical_origin,
                timezone=property_contract.timezone,
                currency=property_contract.currency,
                status="ready",
                metadata_snapshot=metadata,
            )
            session.add(row)
            await session.flush()
            return row
        row.property_type = property_contract.property_type
        row.display_name = property_contract.display_name
        row.canonical_origin = property_contract.canonical_origin
        row.timezone = property_contract.timezone
        row.currency = property_contract.currency
        row.status = "ready"
        row.metadata_snapshot = metadata
        return row

    async def _store_observation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        property_row: MeasurementPropertyRecord,
        observation: MeasurementObservation,
    ) -> bool:
        dimensions_sha = dimension_hash(observation.dimensions)
        existing = await session.scalar(
            select(MeasurementObservationRecord).where(
                MeasurementObservationRecord.measurement_property_id
                == property_row.id,
                MeasurementObservationRecord.metric_key == observation.metric_key,
                MeasurementObservationRecord.dimension_hash == dimensions_sha,
                MeasurementObservationRecord.window_start == observation.window_start,
                MeasurementObservationRecord.window_end == observation.window_end,
                MeasurementObservationRecord.observation_hash
                == observation.observation_hash,
            )
        )
        if existing is not None:
            return False
        session.add(
            MeasurementObservationRecord(
                workspace_id=workspace_id,
                measurement_property_id=property_row.id,
                provider=observation.provider,
                metric_key=observation.metric_key,
                metric_version=observation.metric_version,
                value_microunits=observation.value_microunits,
                dimensions=observation.dimensions,
                dimension_hash=dimensions_sha,
                window_start=observation.window_start,
                window_end=observation.window_end,
                timezone=observation.timezone,
                sample_state=observation.sample_state,
                freshness_state=observation.freshness_state,
                source_definition=observation.source_definition,
                observed_at=observation.observed_at,
                observation_hash=observation.observation_hash,
            )
        )
        return True

    async def _account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        lock: bool = False,
    ) -> MeasurementProviderAccount:
        statement = select(MeasurementProviderAccount).where(
            MeasurementProviderAccount.id == account_id,
            MeasurementProviderAccount.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        account = await session.scalar(statement)
        if account is None:
            raise MeasurementServiceError("Measurement provider account not found")
        if account.status != "ready":
            raise MeasurementServiceError("Measurement provider account is not active")
        return account

    def _validate_account_contract(
        self,
        *,
        provider: MeasurementProvider,
        credential_reference: str,
        capabilities: tuple[MeasurementProviderCapability, ...],
    ) -> None:
        if not credential_reference.startswith(_MANAGED_CREDENTIAL_PREFIXES):
            raise MeasurementServiceError(
                "Measurement credential references must use env:, vault:, secret:, or synthetic:"
            )
        operations = [capability.operation for capability in capabilities]
        if len(operations) != len(set(operations)):
            raise MeasurementServiceError(
                "Measurement capability operations must be unique"
            )
        if provider != "synthetic" and any(
            capability.state in {"granted", "tested"}
            for capability in capabilities
        ):
            raise MeasurementServiceError(
                "Live measurement provider capabilities cannot be granted or tested "
                "before account-level acceptance"
            )
        if provider == "synthetic" and not credential_reference.startswith("synthetic:"):
            raise MeasurementServiceError(
                "Synthetic measurement accounts require a synthetic: credential reference"
            )
