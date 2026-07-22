from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._structured_base_service import (
    StatefulAuditRunService as _BaseStatefulAuditRunService,
)
from catora_api.auditing.custom_rules import current_audit_rule_version_ids
from catora_api.auditing.service import AuditConfigurationError
from catora_api.auditing.structured_rules import (
    StructuredDataRuleConfigurationError,
    ensure_standard_structured_data_rules,
)
from catora_api.db.models.audit import AuditRun


class StatefulAuditRunService(_BaseStatefulAuditRunService):
    async def create_run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        taxonomy_version: str,
        mode: str,
    ) -> AuditRun:
        if mode == "incremental":
            run = await super().create_run(
                session,
                workspace_id=workspace_id,
                requested_by_user_id=requested_by_user_id,
                taxonomy_version=taxonomy_version,
                mode=mode,
            )
            await self._ensure_structured_rules(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
            current_rule_version_set = [
                str(rule_id)
                for rule_id in await current_audit_rule_version_ids(
                    session,
                    workspace_id=workspace_id,
                    taxonomy_version=taxonomy_version,
                )
            ]
            if current_rule_version_set != run.rule_version_set:
                raise AuditConfigurationError(
                    "Incremental audit requires an unchanged rule-version set; run a full audit"
                )
            return run

        await self._ensure_structured_rules(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
        )
        return await super().create_run(
            session,
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            taxonomy_version=taxonomy_version,
            mode=mode,
        )

    async def _ensure_structured_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
    ) -> None:
        try:
            await ensure_standard_structured_data_rules(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
        except StructuredDataRuleConfigurationError as exc:
            raise AuditConfigurationError(str(exc)) from exc
