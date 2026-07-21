from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._duplicate_base_service import (
    StatefulAuditRunService as _BaseStatefulAuditRunService,
)
from catora_api.auditing._duplicate_index import (
    DuplicateContentRecord,
    build_duplicate_content_index,
)
from catora_api.auditing.custom_rules import current_audit_rule_version_ids
from catora_api.auditing.duplicate_rules import (
    DuplicateContentRuleConfigurationError,
    ensure_standard_duplicate_content_rules,
)
from catora_api.auditing.service import AuditConfigurationError, ProductHeader
from catora_api.auditing.types import AttributeSnapshot, EvidenceSnapshot, ProductAuditSnapshot
from catora_api.db.models.audit import AuditRun
from catora_api.db.models.catalog import Category, Product, ProductAttribute


class StatefulAuditRunService(_BaseStatefulAuditRunService):
    def __init__(self) -> None:
        self._duplicate_cache_key: tuple[uuid.UUID, str] | None = None
        self._duplicate_payloads: dict[uuid.UUID, dict[str, object]] = {}

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
            await self._ensure_duplicate_rules(
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

        await self._ensure_duplicate_rules(
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

    async def _ensure_duplicate_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
    ) -> None:
        try:
            await ensure_standard_duplicate_content_rules(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
        except DuplicateContentRuleConfigurationError as exc:
            raise AuditConfigurationError(str(exc)) from exc

    async def _select_headers(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        previous: AuditRun | None,
        all_headers: Sequence[ProductHeader],
    ) -> tuple[tuple[ProductHeader, ...], set[uuid.UUID]]:
        selected, target_product_ids = await super()._select_headers(
            session,
            run=run,
            previous=previous,
            all_headers=all_headers,
        )
        if run.mode != "incremental" or not target_product_ids:
            return selected, target_product_ids
        current_product_ids = {product.id for product, _category in all_headers}
        previous_product_ids = _previous_product_ids(previous)
        expanded_product_ids = current_product_ids | (
            previous_product_ids - current_product_ids
        )
        return tuple(all_headers), expanded_product_ids

    async def _build_snapshots(
        self,
        session: AsyncSession,
        headers: Sequence[ProductHeader],
    ) -> tuple[ProductAuditSnapshot, ...]:
        snapshots = await super()._build_snapshots(session, headers)
        if not snapshots:
            return ()
        workspace_id = cast(uuid.UUID, headers[0][0].workspace_id)
        taxonomy_version = headers[0][1].taxonomy_version
        payloads = await self._load_duplicate_payloads(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
        )
        enriched: list[ProductAuditSnapshot] = []
        for snapshot in snapshots:
            attributes = dict(snapshot.attributes)
            evidence = _content_evidence(attributes)
            attributes["duplicate_content"] = AttributeSnapshot(
                key="duplicate_content",
                value=payloads.get(
                    snapshot.product_id,
                    {
                        "failure_codes": [],
                        "peer_product_ids": [],
                        "match_counts": {},
                    },
                ),
                value_type="object",
                value_state="present",
                evidence=evidence,
            )
            enriched.append(replace(snapshot, attributes=attributes))
        return tuple(enriched)

    async def _load_duplicate_payloads(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
    ) -> Mapping[uuid.UUID, dict[str, object]]:
        cache_key = (workspace_id, taxonomy_version)
        if self._duplicate_cache_key == cache_key:
            return self._duplicate_payloads
        rows = (
            await session.execute(
                select(Product.id, Product.title, Category.key)
                .join(Category, Category.id == Product.primary_category_id)
                .where(
                    Product.workspace_id == workspace_id,
                    Product.deleted_at.is_(None),
                    Product.status == "active",
                    Category.workspace_id == workspace_id,
                    Category.taxonomy_version == taxonomy_version,
                    Category.is_immutable.is_(True),
                )
                .order_by(Product.id)
            )
        ).all()
        product_ids = [product_id for product_id, _title, _category_key in rows]
        descriptions: dict[uuid.UUID, str] = {}
        if product_ids:
            description_rows = (
                await session.execute(
                    select(ProductAttribute.product_id, ProductAttribute.value)
                    .where(
                        ProductAttribute.workspace_id == workspace_id,
                        ProductAttribute.product_id.in_(product_ids),
                        ProductAttribute.variant_id.is_(None),
                        ProductAttribute.key == "description",
                        ProductAttribute.value_state == "present",
                    )
                    .order_by(ProductAttribute.product_id, ProductAttribute.id)
                )
            ).all()
            for product_id, value in description_rows:
                if isinstance(value, str):
                    descriptions[product_id] = value
        records = tuple(
            DuplicateContentRecord(
                product_id=product_id,
                category_key=category_key,
                title=title,
                description=descriptions.get(product_id),
            )
            for product_id, title, category_key in rows
        )
        index = build_duplicate_content_index(records)
        self._duplicate_cache_key = cache_key
        self._duplicate_payloads = {
            product_id: result.payload() for product_id, result in index.items()
        }
        return self._duplicate_payloads


def _previous_product_ids(previous: AuditRun | None) -> set[uuid.UUID]:
    if previous is None:
        return set()
    try:
        return {uuid.UUID(value) for value in previous.product_snapshot_hashes}
    except ValueError as exc:
        raise AuditConfigurationError(
            "Incremental baseline contains an invalid product identifier"
        ) from exc


def _content_evidence(
    attributes: Mapping[str, AttributeSnapshot],
) -> tuple[EvidenceSnapshot, ...]:
    unique: dict[tuple[str, str, str | None, str | None], EvidenceSnapshot] = {}
    for field_key in ("title", "description"):
        attribute = attributes.get(field_key)
        if attribute is None:
            continue
        for item in attribute.evidence:
            identity = (
                str(item.source_record_id),
                item.field_path,
                item.excerpt,
                item.checksum,
            )
            unique[identity] = item
    return tuple(unique[key] for key in sorted(unique))
