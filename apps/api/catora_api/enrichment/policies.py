from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.workflow import WorkspaceEnrichmentPolicy
from catora_api.enrichment.types import BrandControls, EnrichmentRequest, FieldKey


class EnrichmentPolicyConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EffectiveEnrichmentPolicy:
    brand_controls: BrandControls
    max_run_budget_microunits: int


class WorkspaceEnrichmentPolicyService:
    async def get(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
    ) -> WorkspaceEnrichmentPolicy | None:
        policy = await session.scalar(
            select(WorkspaceEnrichmentPolicy).where(
                WorkspaceEnrichmentPolicy.workspace_id == workspace_id
            )
        )
        return policy if isinstance(policy, WorkspaceEnrichmentPolicy) else None

    async def resolve(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        requested_controls: BrandControls,
        system_max_run_budget_microunits: int,
    ) -> EffectiveEnrichmentPolicy:
        policy = await self.get(session, workspace_id=workspace_id)
        if policy is None:
            return EffectiveEnrichmentPolicy(
                brand_controls=requested_controls,
                max_run_budget_microunits=system_max_run_budget_microunits,
            )
        try:
            workspace_controls = BrandControls.model_validate(policy.brand_controls)
        except ValidationError as exc:
            raise EnrichmentPolicyConfigurationError(
                "Workspace enrichment policy is invalid"
            ) from exc
        workspace_maximum = policy.max_run_budget_microunits
        effective_maximum = (
            system_max_run_budget_microunits
            if workspace_maximum is None
            else min(system_max_run_budget_microunits, workspace_maximum)
        )
        return EffectiveEnrichmentPolicy(
            brand_controls=merge_brand_controls(workspace_controls, requested_controls),
            max_run_budget_microunits=effective_maximum,
        )

    async def apply(
        self,
        session: AsyncSession,
        *,
        request: EnrichmentRequest,
        max_run_budget_microunits: int,
    ) -> tuple[EnrichmentRequest, int]:
        effective = await self.resolve(
            session,
            workspace_id=request.workspace_id,
            requested_controls=request.brand_controls,
            system_max_run_budget_microunits=max_run_budget_microunits,
        )
        return (
            request.model_copy(
                update={"brand_controls": effective.brand_controls},
            ),
            effective.max_run_budget_microunits,
        )

    async def set(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        brand_controls: BrandControls,
        max_run_budget_microunits: int | None,
    ) -> WorkspaceEnrichmentPolicy:
        policy = await self.get(session, workspace_id=workspace_id)
        payload = brand_controls.model_dump(mode="json")
        if policy is None:
            policy = WorkspaceEnrichmentPolicy(
                workspace_id=workspace_id,
                brand_controls=payload,
                max_run_budget_microunits=max_run_budget_microunits,
            )
            session.add(policy)
            await session.flush()
            return policy
        policy.brand_controls = payload
        policy.max_run_budget_microunits = max_run_budget_microunits
        await session.flush()
        return policy


def merge_brand_controls(
    workspace: BrandControls,
    requested: BrandControls,
) -> BrandControls:
    maximum_lengths: dict[FieldKey, int] = dict(workspace.maximum_lengths)
    for field_key, requested_limit in requested.maximum_lengths.items():
        workspace_limit = maximum_lengths.get(field_key)
        maximum_lengths[field_key] = (
            requested_limit
            if workspace_limit is None
            else min(workspace_limit, requested_limit)
        )
    return BrandControls(
        tone=workspace.tone,
        banned_claims=_merge_terms(workspace.banned_claims, requested.banned_claims),
        required_terms=_merge_terms(workspace.required_terms, requested.required_terms),
        locked_fields=_merge_fields(workspace.locked_fields, requested.locked_fields),
        maximum_lengths=maximum_lengths,
    )


def _merge_terms(primary: tuple[str, ...], additional: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in (*primary, *additional):
        identity = item.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return tuple(result)


def _merge_fields(
    primary: tuple[FieldKey, ...],
    additional: tuple[FieldKey, ...],
) -> tuple[FieldKey, ...]:
    return tuple(dict.fromkeys((*primary, *additional)))
