from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._content_base_service import (
    StatefulAuditRunService as _BaseStatefulAuditRunService,
)
from catora_api.auditing.content_rules import (
    ContentRuleConfigurationError,
    ensure_standard_content_rules,
)
from catora_api.auditing.custom_rules import current_audit_rule_version_ids
from catora_api.auditing.service import AuditConfigurationError, ProductHeader
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
)
from catora_api.db.models.audit import AuditRun
from catora_api.db.models.catalog import EvidenceReference


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
            await self._ensure_content_rules(
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

        await self._ensure_content_rules(
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

    async def _ensure_content_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
    ) -> None:
        try:
            await ensure_standard_content_rules(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
        except ContentRuleConfigurationError as exc:
            raise AuditConfigurationError(str(exc)) from exc

    async def _build_snapshots(
        self,
        session: AsyncSession,
        headers: Sequence[ProductHeader],
    ) -> tuple[ProductAuditSnapshot, ...]:
        snapshots = await super()._build_snapshots(session, headers)
        if not snapshots:
            return ()

        workspace_id = cast(uuid.UUID, headers[0][0].workspace_id)
        product_ids = [product.id for product, _category in headers]
        evidence = (
            await session.scalars(
                select(EvidenceReference)
                .where(
                    EvidenceReference.workspace_id == workspace_id,
                    EvidenceReference.product_id.in_(product_ids),
                    EvidenceReference.variant_id.is_(None),
                    EvidenceReference.attribute_id.is_(None),
                )
                .order_by(
                    EvidenceReference.product_id,
                    EvidenceReference.field_path,
                    EvidenceReference.id,
                )
            )
        ).all()
        evidence_by_product: dict[uuid.UUID, list[EvidenceSnapshot]] = defaultdict(list)
        for reference in evidence:
            if reference.product_id is not None:
                evidence_by_product[reference.product_id].append(
                    EvidenceSnapshot(
                        source_record_id=reference.source_record_id,
                        field_path=reference.field_path,
                        excerpt=reference.excerpt,
                        checksum=reference.checksum,
                    )
                )

        product_by_id = {product.id: product for product, _category in headers}
        enriched: list[ProductAuditSnapshot] = []
        for snapshot in snapshots:
            product = product_by_id[snapshot.product_id]
            attributes = dict(snapshot.attributes)
            attributes["title"] = AttributeSnapshot(
                key="title",
                value=product.title,
                value_type="string",
                evidence=tuple(evidence_by_product.get(product.id, [])),
            )
            enriched.append(replace(snapshot, attributes=attributes))
        return tuple(enriched)
