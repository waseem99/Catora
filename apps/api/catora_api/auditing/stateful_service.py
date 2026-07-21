from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._image_base_service import (
    StatefulAuditRunService as _BaseStatefulAuditRunService,
)
from catora_api.auditing.custom_rules import current_audit_rule_version_ids
from catora_api.auditing.image_rules import (
    ImageRuleConfigurationError,
    ensure_standard_image_rules,
)
from catora_api.auditing.service import AuditConfigurationError, ProductHeader
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
)
from catora_api.db.models.audit import AuditRun
from catora_api.db.models.catalog import EvidenceReference, ProductImage


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
            await self._ensure_image_rules(
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

        await self._ensure_image_rules(
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

    async def _ensure_image_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
    ) -> None:
        try:
            await ensure_standard_image_rules(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
        except ImageRuleConfigurationError as exc:
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
        images = (
            await session.scalars(
                select(ProductImage)
                .where(
                    ProductImage.workspace_id == workspace_id,
                    ProductImage.product_id.in_(product_ids),
                )
                .order_by(
                    ProductImage.product_id,
                    ProductImage.position,
                    ProductImage.id,
                )
            )
        ).all()
        images_by_product: dict[uuid.UUID, list[ProductImage]] = defaultdict(list)
        image_urls: set[str] = set()
        for image in images:
            images_by_product[image.product_id].append(image)
            image_urls.add(image.url)

        evidence_by_product_and_excerpt: dict[
            tuple[uuid.UUID, str], list[EvidenceSnapshot]
        ] = defaultdict(list)
        if image_urls:
            evidence = (
                await session.scalars(
                    select(EvidenceReference)
                    .where(
                        EvidenceReference.workspace_id == workspace_id,
                        EvidenceReference.product_id.in_(product_ids),
                        EvidenceReference.variant_id.is_(None),
                        EvidenceReference.attribute_id.is_(None),
                        EvidenceReference.excerpt.in_(sorted(image_urls)),
                    )
                    .order_by(
                        EvidenceReference.product_id,
                        EvidenceReference.field_path,
                        EvidenceReference.id,
                    )
                )
            ).all()
            for reference in evidence:
                if reference.product_id is not None and reference.excerpt:
                    evidence_by_product_and_excerpt[
                        (reference.product_id, reference.excerpt)
                    ].append(
                        EvidenceSnapshot(
                            source_record_id=reference.source_record_id,
                            field_path=reference.field_path,
                            excerpt=reference.excerpt,
                            checksum=reference.checksum,
                        )
                    )

        enriched: list[ProductAuditSnapshot] = []
        for snapshot in snapshots:
            attributes = dict(snapshot.attributes)
            image_evidence: list[EvidenceSnapshot] = []
            image_payloads: list[dict[str, object]] = []
            for image in images_by_product.get(snapshot.product_id, []):
                image_payloads.append(
                    {
                        "variant_id": str(image.variant_id) if image.variant_id else None,
                        "url": image.url,
                        "alt_text": image.alt_text,
                        "position": image.position,
                        "checksum": image.checksum,
                    }
                )
                image_evidence.extend(
                    evidence_by_product_and_excerpt.get(
                        (snapshot.product_id, image.url),
                        [],
                    )
                )
            attributes["images"] = AttributeSnapshot(
                key="images",
                value=image_payloads,
                value_type="list",
                value_state="present" if image_payloads else "missing",
                evidence=tuple(image_evidence),
            )
            enriched.append(replace(snapshot, attributes=attributes))
        return tuple(enriched)
