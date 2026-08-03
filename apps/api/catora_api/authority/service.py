from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.authority.evaluator import canonical_hash, derive_opportunity
from catora_api.authority.models import (
    AuthorityCapability,
    AuthorityObservation,
    AuthorityProvider,
    OutreachDecision,
    OutreachDraft,
    SuppressionRecord,
)
from catora_api.authority.provider import AuthoritySourceProvider
from catora_api.db.models import AuditEvent
from catora_api.db.models.authority import (
    AuthorityObservationRecord,
    AuthorityOpportunityRecord,
    AuthorityOutreachDecisionRecord,
    AuthorityOutreachDraftRecord,
    AuthorityProviderAccount,
    AuthoritySuppressionRecord,
)

_MANAGED_CREDENTIAL_PREFIXES = ("env:", "vault:", "secret:", "synthetic:")


class AuthorityServiceError(ValueError):
    pass


class AuthorityService:
    async def create_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        provider: AuthorityProvider,
        external_account_id: str,
        credential_reference: str,
        capabilities: tuple[AuthorityCapability, ...],
    ) -> AuthorityProviderAccount:
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
            select(AuthorityProviderAccount).where(
                AuthorityProviderAccount.workspace_id == workspace_id,
                AuthorityProviderAccount.provider == provider,
                AuthorityProviderAccount.external_account_id == external_account_id,
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
            raise AuthorityServiceError(
                "Authority provider account already exists with different configuration"
            )
        row = AuthorityProviderAccount(
            workspace_id=workspace_id,
            provider=provider,
            external_account_id=external_account_id,
            credential_reference=credential_reference,
            capabilities=capability_payload,
            status="ready",
            sync_checkpoint={},
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.account_connected",
                entity_type="authority_provider_account",
                entity_id=row.id,
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
        return row

    async def sync_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        account_id: uuid.UUID,
        provider: AuthoritySourceProvider,
    ) -> dict[str, int]:
        account = await self._account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            lock=True,
        )
        accepted = duplicate = prohibited = opportunities = 0
        async for observation in provider.observations(
            checkpoint={
                str(key): str(value)
                for key, value in account.sync_checkpoint.items()
            }
        ):
            if observation.provider != account.provider:
                raise AuthorityServiceError(
                    "Authority observation provider does not match its account"
                )
            existing = await session.scalar(
                select(AuthorityObservationRecord).where(
                    AuthorityObservationRecord.provider_account_id == account.id,
                    AuthorityObservationRecord.external_observation_id
                    == observation.external_observation_id,
                    AuthorityObservationRecord.observation_hash
                    == observation.observation_hash,
                )
            )
            if existing is not None:
                duplicate += 1
                continue
            row = AuthorityObservationRecord(
                workspace_id=workspace_id,
                provider_account_id=account.id,
                external_observation_id=observation.external_observation_id,
                observation_type=observation.observation_type,
                brand_id=observation.brand_id,
                location_id=observation.location_id,
                source_url=observation.source_url,
                target_url=observation.target_url,
                source_title=observation.source_title,
                anchor_or_mention_text=observation.anchor_or_mention_text,
                provider_metrics=observation.provider_metrics,
                identity_state=observation.identity_state,
                identity_method=observation.identity_method,
                link_state=observation.link_state,
                nofollow=observation.nofollow,
                sponsored=observation.sponsored,
                observed_at=observation.observed_at,
                source_updated_at=observation.source_updated_at,
                observation_hash=observation.observation_hash,
            )
            session.add(row)
            await session.flush()
            accepted += 1
            opportunity = derive_opportunity(observation)
            if opportunity is None:
                prohibited += 1
                continue
            fingerprint = canonical_hash(
                {
                    "observation": observation.observation_hash,
                    "type": opportunity.opportunity_type,
                    "version": opportunity.score_version,
                }
            )
            existing_opportunity = await session.scalar(
                select(AuthorityOpportunityRecord).where(
                    AuthorityOpportunityRecord.workspace_id == workspace_id,
                    AuthorityOpportunityRecord.opportunity_fingerprint == fingerprint,
                )
            )
            if existing_opportunity is None:
                session.add(
                    AuthorityOpportunityRecord(
                        workspace_id=workspace_id,
                        authority_observation_id=row.id,
                        opportunity_type=opportunity.opportunity_type,
                        state=opportunity.state,
                        risk_state=opportunity.risk_state,
                        title=opportunity.title,
                        rationale=opportunity.rationale,
                        verification_method=opportunity.verification_method,
                        owner_role=opportunity.owner_role,
                        evidence_hashes=list(opportunity.evidence_hashes),
                        score_basis_points=opportunity.score_basis_points,
                        score_version=opportunity.score_version,
                        opportunity_fingerprint=fingerprint,
                    )
                )
                opportunities += 1
        account.sync_checkpoint = {
            "last_synced_at": datetime.now(UTC).isoformat(),
            "accepted": accepted,
            "duplicate": duplicate,
        }
        summary = {
            "accepted": accepted,
            "duplicate": duplicate,
            "prohibited": prohibited,
            "opportunities": opportunities,
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.sync_completed",
                entity_type="authority_provider_account",
                entity_id=account.id,
                payload=summary,
            )
        )
        await session.commit()
        return summary

    async def create_suppression(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        suppression: SuppressionRecord,
    ) -> AuthoritySuppressionRecord:
        existing = await session.scalar(
            select(AuthoritySuppressionRecord).where(
                AuthoritySuppressionRecord.workspace_id == workspace_id,
                AuthoritySuppressionRecord.normalized_target
                == suppression.normalized_target,
            )
        )
        if existing is not None:
            return existing
        row = AuthoritySuppressionRecord(
            workspace_id=workspace_id,
            normalized_target=suppression.normalized_target,
            reason=suppression.reason,
            effective_at=suppression.effective_at,
            expires_at=suppression.expires_at,
            created_by_user_id=actor_user_id,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.suppression_created",
                entity_type="authority_suppression",
                entity_id=row.id,
                payload={"reason": suppression.reason},
            )
        )
        await session.commit()
        return row

    async def create_outreach_draft(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        normalized_target: str,
        draft: OutreachDraft,
    ) -> AuthorityOutreachDraftRecord:
        opportunity = await session.scalar(
            select(AuthorityOpportunityRecord).where(
                AuthorityOpportunityRecord.id == draft.opportunity_id,
                AuthorityOpportunityRecord.workspace_id == workspace_id,
            )
        )
        if opportunity is None:
            raise AuthorityServiceError("Authority opportunity not found")
        if opportunity.risk_state == "prohibited" or opportunity.state == "suppressed":
            raise AuthorityServiceError(
                "Suppressed or prohibited opportunities cannot be drafted"
            )
        suppression = await session.scalar(
            select(AuthoritySuppressionRecord).where(
                AuthoritySuppressionRecord.workspace_id == workspace_id,
                AuthoritySuppressionRecord.normalized_target == normalized_target,
            )
        )
        if suppression is not None and (
            suppression.expires_at is None
            or suppression.expires_at > datetime.now(UTC)
        ):
            raise AuthorityServiceError("Outreach target is suppressed")
        latest = await session.scalar(
            select(AuthorityOutreachDraftRecord.draft_version)
            .where(
                AuthorityOutreachDraftRecord.workspace_id == workspace_id,
                AuthorityOutreachDraftRecord.opportunity_id == opportunity.id,
            )
            .order_by(AuthorityOutreachDraftRecord.draft_version.desc())
            .limit(1)
        )
        row = AuthorityOutreachDraftRecord(
            workspace_id=workspace_id,
            opportunity_id=opportunity.id,
            draft_version=(latest or 0) + 1,
            channel=draft.channel,
            subject=draft.subject,
            body=draft.body,
            factual_claims=list(draft.factual_claims),
            evidence_hashes=list(draft.evidence_hashes),
            status="draft",
            suppression_checked=True,
            legal_basis_confirmed=True,
            generated_by_user_id=actor_user_id,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.outreach_draft_created",
                entity_type="authority_outreach_draft",
                entity_id=row.id,
                payload={
                    "opportunity_id": str(opportunity.id),
                    "draft_version": row.draft_version,
                    "send_allowed": False,
                },
            )
        )
        await session.commit()
        return row

    async def decide_outreach_draft(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        draft_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        decision: OutreachDecision,
        reason: str,
    ) -> AuthorityOutreachDecisionRecord:
        draft = await session.scalar(
            select(AuthorityOutreachDraftRecord).where(
                AuthorityOutreachDraftRecord.id == draft_id,
                AuthorityOutreachDraftRecord.workspace_id == workspace_id,
            )
        )
        if draft is None:
            raise AuthorityServiceError("Outreach draft not found")
        if draft.status != "draft":
            raise AuthorityServiceError("Only draft outreach can receive a decision")
        existing = await session.scalar(
            select(AuthorityOutreachDecisionRecord).where(
                AuthorityOutreachDecisionRecord.workspace_id == workspace_id,
                AuthorityOutreachDecisionRecord.draft_id == draft.id,
            )
        )
        if existing is not None:
            raise AuthorityServiceError("Outreach draft already has a decision")
        draft.status = decision
        row = AuthorityOutreachDecisionRecord(
            workspace_id=workspace_id,
            draft_id=draft.id,
            decision=decision,
            reason=reason,
            decided_by_user_id=actor_user_id,
            decided_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.outreach_decided",
                entity_type="authority_outreach_draft",
                entity_id=draft.id,
                payload={"decision": decision, "send_allowed": False},
            )
        )
        await session.commit()
        return row

    async def disconnect_account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> AuthorityProviderAccount:
        account = await self._account(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            lock=True,
        )
        account.status = "disconnected"
        account.credential_reference = "revoked"
        account.disconnected_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="authority.account_disconnected",
                entity_type="authority_provider_account",
                entity_id=account.id,
                payload={"provider": account.provider},
            )
        )
        await session.commit()
        return account

    async def _account(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        account_id: uuid.UUID,
        lock: bool = False,
    ) -> AuthorityProviderAccount:
        statement = select(AuthorityProviderAccount).where(
            AuthorityProviderAccount.id == account_id,
            AuthorityProviderAccount.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            raise AuthorityServiceError("Authority provider account not found")
        if row.status != "ready":
            raise AuthorityServiceError("Authority provider account is not active")
        return row

    def _validate_account_contract(
        self,
        *,
        provider: AuthorityProvider,
        credential_reference: str,
        capabilities: tuple[AuthorityCapability, ...],
    ) -> None:
        if not credential_reference.startswith(_MANAGED_CREDENTIAL_PREFIXES):
            raise AuthorityServiceError(
                "Authority credential references must use env:, vault:, secret:, or synthetic:"
            )
        operations = [item.operation for item in capabilities]
        if len(operations) != len(set(operations)):
            raise AuthorityServiceError("Authority capability operations must be unique")
        if provider != "synthetic" and any(
            item.state in {"granted", "tested"} for item in capabilities
        ):
            raise AuthorityServiceError(
                "Live authority capabilities cannot be granted or tested before account acceptance"
            )
        if provider == "synthetic" and not credential_reference.startswith("synthetic:"):
            raise AuthorityServiceError(
                "Synthetic authority accounts require a synthetic: credential reference"
            )
