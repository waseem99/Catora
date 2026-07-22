from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import (
    Category,
    EvidenceReference,
    Product,
    ProductAttribute,
    ProductVariant,
)
from catora_api.db.models.intents import BuyerIntent, IntentProductMatch, IntentRun
from catora_api.intents.matcher import evaluate_intent
from catora_api.intents.types import (
    CanonicalFact,
    FactEvidence,
    FactValue,
    IntentMatchResult,
    IntentMatchStatus,
    IntentProductCandidate,
    StructuredBuyerIntent,
    ValueState,
)


class IntentRunError(RuntimeError):
    pass


class IntentRunNotFoundError(IntentRunError):
    pass


class IntentRunTargetError(IntentRunError):
    pass


class IntentRunDataError(IntentRunError):
    pass


@dataclass(frozen=True, slots=True)
class IntentRunSummary:
    target_count: int
    product_count: int
    confident_match_count: int
    possible_match_missing_data_count: int
    non_match_count: int
    insufficient_category_data_count: int


@dataclass(frozen=True, slots=True)
class PersistedIntentRun:
    run: IntentRun
    intent: BuyerIntent
    matches: tuple[IntentProductMatch, ...]
    summary: IntentRunSummary


@dataclass(frozen=True, slots=True)
class IntentMatchPage:
    items: tuple[IntentProductMatch, ...]
    total: int


class IntentRunService:
    async def execute(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        lineage_id: uuid.UUID,
        intent_version: int,
        product_ids: tuple[uuid.UUID, ...] = (),
    ) -> PersistedIntentRun:
        if len(product_ids) != len(set(product_ids)):
            raise IntentRunTargetError("Intent-run product identifiers must be unique")
        intent = await session.scalar(
            select(BuyerIntent).where(
                BuyerIntent.workspace_id == workspace_id,
                BuyerIntent.lineage_id == lineage_id,
                BuyerIntent.version == intent_version,
                BuyerIntent.approval_status == "approved",
            )
        )
        if intent is None:
            raise IntentRunNotFoundError("Approved buyer intent version not found")
        structured = StructuredBuyerIntent.model_validate(intent.structured_intent)

        product_query = select(Product).where(
            Product.workspace_id == workspace_id,
            Product.status == "active",
            Product.deleted_at.is_(None),
        )
        if product_ids:
            product_query = product_query.where(Product.id.in_(product_ids))
        products = tuple(
            (await session.scalars(product_query.order_by(Product.id))).all()
        )
        if product_ids and {item.id for item in products} != set(product_ids):
            raise IntentRunTargetError("One or more intent-run products were not found")

        loaded_product_ids = tuple(item.id for item in products)
        categories = await _categories(session, workspace_id, products)
        variants = await _variants(session, workspace_id, loaded_product_ids)
        attributes = await _attributes(session, workspace_id, loaded_product_ids)
        evidence = await _evidence(session, workspace_id, attributes)
        candidates = build_candidates(
            products,
            categories,
            variants,
            attributes,
            evidence,
        )
        snapshot_hash = source_snapshot_hash(intent, structured, candidates)

        run = IntentRun(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            buyer_intent_id=intent.id,
            status="running",
            source_snapshot_hash=snapshot_hash,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        session.add(run)
        await session.flush()

        matches = tuple(
            _match_record(
                workspace_id=workspace_id,
                run_id=run.id,
                result=evaluate_intent(structured, candidate),
            )
            for candidate in candidates
        )
        for match in matches:
            session.add(match)
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.flush()
        return PersistedIntentRun(
            run=run,
            intent=intent,
            matches=matches,
            summary=summarize_matches(matches),
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> tuple[IntentRun, BuyerIntent, IntentRunSummary]:
        row = (
            await session.execute(
                select(IntentRun, BuyerIntent)
                .join(BuyerIntent, BuyerIntent.id == IntentRun.buyer_intent_id)
                .where(
                    IntentRun.id == run_id,
                    IntentRun.workspace_id == workspace_id,
                    BuyerIntent.workspace_id == workspace_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise IntentRunNotFoundError("Intent run not found")
        run, intent = row
        return run, intent, await _persisted_summary(session, workspace_id, run_id)

    async def list_matches(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        match_status: IntentMatchStatus | None,
        offset: int,
        limit: int,
    ) -> IntentMatchPage:
        run_exists = await session.scalar(
            select(IntentRun.id).where(
                IntentRun.id == run_id,
                IntentRun.workspace_id == workspace_id,
            )
        )
        if run_exists is None:
            raise IntentRunNotFoundError("Intent run not found")
        query = select(IntentProductMatch).where(
            IntentProductMatch.workspace_id == workspace_id,
            IntentProductMatch.intent_run_id == run_id,
        )
        if match_status is not None:
            query = query.where(IntentProductMatch.status == match_status)
        total = int(
            (
                await session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
            )
            or 0
        )
        items = tuple(
            (
                await session.scalars(
                    query.order_by(
                        IntentProductMatch.product_id,
                        IntentProductMatch.variant_id.asc().nulls_first(),
                        IntentProductMatch.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return IntentMatchPage(items=items, total=total)


async def _categories(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    products: tuple[Product, ...],
) -> tuple[Category, ...]:
    category_ids = tuple(
        sorted(
            {
                item.primary_category_id
                for item in products
                if item.primary_category_id is not None
            }
        )
    )
    if not category_ids:
        return ()
    return tuple(
        (
            await session.scalars(
                select(Category)
                .where(
                    Category.workspace_id == workspace_id,
                    Category.id.in_(category_ids),
                )
                .order_by(Category.id)
            )
        ).all()
    )


async def _variants(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    product_ids: tuple[uuid.UUID, ...],
) -> tuple[ProductVariant, ...]:
    if not product_ids:
        return ()
    return tuple(
        (
            await session.scalars(
                select(ProductVariant)
                .where(
                    ProductVariant.workspace_id == workspace_id,
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.deleted_at.is_(None),
                )
                .order_by(ProductVariant.product_id, ProductVariant.id)
            )
        ).all()
    )


async def _attributes(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    product_ids: tuple[uuid.UUID, ...],
) -> tuple[ProductAttribute, ...]:
    if not product_ids:
        return ()
    return tuple(
        (
            await session.scalars(
                select(ProductAttribute)
                .where(
                    ProductAttribute.workspace_id == workspace_id,
                    ProductAttribute.product_id.in_(product_ids),
                )
                .order_by(
                    ProductAttribute.product_id,
                    ProductAttribute.variant_id.asc().nulls_first(),
                    ProductAttribute.key,
                    ProductAttribute.id,
                )
            )
        ).all()
    )


async def _evidence(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    attributes: tuple[ProductAttribute, ...],
) -> tuple[EvidenceReference, ...]:
    attribute_ids = tuple(item.id for item in attributes)
    if not attribute_ids:
        return ()
    return tuple(
        (
            await session.scalars(
                select(EvidenceReference)
                .where(
                    EvidenceReference.workspace_id == workspace_id,
                    EvidenceReference.attribute_id.in_(attribute_ids),
                )
                .order_by(
                    EvidenceReference.attribute_id,
                    EvidenceReference.field_path,
                    EvidenceReference.id,
                )
            )
        ).all()
    )


def build_candidates(
    products: tuple[Product, ...],
    categories: tuple[Category, ...],
    variants: tuple[ProductVariant, ...],
    attributes: tuple[ProductAttribute, ...],
    evidence: tuple[EvidenceReference, ...],
) -> tuple[IntentProductCandidate, ...]:
    category_keys = {item.id: item.key for item in categories}
    variants_by_product: defaultdict[uuid.UUID, list[ProductVariant]] = defaultdict(list)
    for variant in variants:
        variants_by_product[variant.product_id].append(variant)

    evidence_by_attribute: defaultdict[uuid.UUID, list[EvidenceReference]] = defaultdict(list)
    for reference in evidence:
        if reference.attribute_id is not None:
            evidence_by_attribute[reference.attribute_id].append(reference)

    facts_by_scope: defaultdict[
        tuple[uuid.UUID, uuid.UUID | None], dict[str, CanonicalFact]
    ] = defaultdict(dict)
    for attribute in attributes:
        scope = (attribute.product_id, attribute.variant_id)
        if attribute.key in facts_by_scope[scope]:
            raise IntentRunDataError(
                "Multiple canonical attributes exist for the same product, variant and field"
            )
        facts_by_scope[scope][attribute.key] = _fact(
            attribute,
            evidence_by_attribute[attribute.id],
        )

    candidates: list[IntentProductCandidate] = []
    for product in sorted(products, key=lambda item: item.id):
        product_facts = facts_by_scope.get((product.id, None), {})
        category_key = (
            category_keys.get(product.primary_category_id)
            if product.primary_category_id is not None
            else None
        )
        product_variants = sorted(
            variants_by_product.get(product.id, []),
            key=lambda item: item.id,
        )
        if not product_variants:
            candidates.append(
                IntentProductCandidate(
                    product_id=product.id,
                    variant_id=None,
                    category_key=category_key,
                    facts=_sorted_facts(product_facts),
                )
            )
            continue
        for variant in product_variants:
            merged = dict(product_facts)
            merged.update(facts_by_scope.get((product.id, variant.id), {}))
            candidates.append(
                IntentProductCandidate(
                    product_id=product.id,
                    variant_id=variant.id,
                    category_key=category_key,
                    facts=_sorted_facts(merged),
                )
            )
    return tuple(candidates)


def _sorted_facts(facts: dict[str, CanonicalFact]) -> tuple[CanonicalFact, ...]:
    return tuple(facts[key] for key in sorted(facts))


def _fact(
    attribute: ProductAttribute,
    evidence: list[EvidenceReference],
) -> CanonicalFact:
    state = cast(ValueState, attribute.value_state)
    value = _attribute_value(attribute.value) if state == "present" else None
    if state == "present" and value is None:
        raise IntentRunDataError(
            f"Present canonical attribute {attribute.key!r} has no value"
        )
    return CanonicalFact(
        field_key=attribute.key,
        value=value,
        value_state=state,
        unit=attribute.unit,
        evidence=tuple(
            FactEvidence(
                source_record_id=item.source_record_id,
                field_path=item.field_path,
                excerpt=item.excerpt,
                checksum=item.checksum,
            )
            for item in evidence
        ),
    )


def _attribute_value(value: object) -> FactValue:
    if value is None:
        return None
    if isinstance(value, bool | str | int | float):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return tuple(_json_scalar(item) for item in value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_scalar(value: object) -> str | int | float | bool:
    if isinstance(value, bool | str | int | float):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_snapshot_hash(
    intent: BuyerIntent,
    structured: StructuredBuyerIntent,
    candidates: tuple[IntentProductCandidate, ...],
) -> str:
    payload = {
        "intent_id": str(intent.id),
        "lineage_id": str(intent.lineage_id),
        "version": intent.version,
        "structured_intent": structured.model_dump(mode="json"),
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _match_record(
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    result: IntentMatchResult,
) -> IntentProductMatch:
    return IntentProductMatch(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        intent_run_id=run_id,
        product_id=result.product_id,
        variant_id=result.variant_id,
        status=result.status,
        score=Decimal(result.soft_score_basis_points) / Decimal(10_000),
        explanation=result.model_dump(mode="json"),
    )


def summarize_matches(matches: tuple[IntentProductMatch, ...]) -> IntentRunSummary:
    counts: defaultdict[str, int] = defaultdict(int)
    product_ids: set[uuid.UUID] = set()
    for match in matches:
        counts[match.status] += 1
        product_ids.add(match.product_id)
    return _summary(counts, len(matches), len(product_ids))


async def _persisted_summary(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
) -> IntentRunSummary:
    rows = (
        await session.execute(
            select(IntentProductMatch.status, func.count())
            .where(
                IntentProductMatch.workspace_id == workspace_id,
                IntentProductMatch.intent_run_id == run_id,
            )
            .group_by(IntentProductMatch.status)
        )
    ).all()
    counts = defaultdict(int, {str(status): int(count) for status, count in rows})
    product_count = int(
        (
            await session.scalar(
                select(func.count(func.distinct(IntentProductMatch.product_id))).where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentProductMatch.intent_run_id == run_id,
                )
            )
        )
        or 0
    )
    return _summary(counts, sum(counts.values()), product_count)


def _summary(
    counts: defaultdict[str, int],
    target_count: int,
    product_count: int,
) -> IntentRunSummary:
    return IntentRunSummary(
        target_count=target_count,
        product_count=product_count,
        confident_match_count=counts["confident_match"],
        possible_match_missing_data_count=counts["possible_match_missing_data"],
        non_match_count=counts["non_match"],
        insufficient_category_data_count=counts["insufficient_category_data"],
    )
