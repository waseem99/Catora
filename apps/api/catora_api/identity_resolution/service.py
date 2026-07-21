from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import combinations
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import Product, ProductAttribute, ProductVariant
from catora_api.db.models.catalog_identity import (
    CommercialProductIdentity,
    ProductIdentityCandidate,
    ProductIdentityMembership,
)

ALGORITHM_VERSION = "catalog-identity-v1"
_MAX_BLOCK_SIZE = 100
_IDENTIFIER_PATTERN = re.compile(r"[^a-z0-9]+")
_TITLE_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class CatalogIdentityNotFoundError(ValueError):
    pass


class CatalogIdentityConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CandidateRefreshSummary:
    products_considered: int
    candidates_created: int
    candidates_updated: int
    candidates_superseded: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class _ProductProfile:
    product: Product
    title_key: str
    title_tokens: tuple[str, ...]
    brands: frozenset[str]
    gtins: frozenset[str]
    mpns: frozenset[str]
    skus: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CandidateProposal:
    left_product_id: uuid.UUID
    right_product_id: uuid.UUID
    match_type: str
    score_basis_points: int
    signals: tuple[dict[str, object], ...]


class CatalogIdentityService:
    async def refresh_candidates(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        max_products: int = 1000,
    ) -> CandidateRefreshSummary:
        products = (
            await session.scalars(
                select(Product)
                .where(
                    Product.workspace_id == workspace_id,
                    Product.deleted_at.is_(None),
                    Product.status == "active",
                )
                .order_by(Product.id)
                .limit(max_products + 1)
            )
        ).all()
        truncated = len(products) > max_products
        products = products[:max_products]
        profiles = await self._profiles(
            session,
            workspace_id=workspace_id,
            products=products,
        )
        proposals = self._proposals(profiles)
        existing = (
            await session.scalars(
                select(ProductIdentityCandidate).where(
                    ProductIdentityCandidate.workspace_id == workspace_id,
                    ProductIdentityCandidate.algorithm_version == ALGORITHM_VERSION,
                )
            )
        ).all()
        existing_by_pair = {
            _pair(candidate.left_product_id, candidate.right_product_id): candidate
            for candidate in existing
        }

        created = 0
        updated = 0
        for pair, proposal in proposals.items():
            candidate = existing_by_pair.get(pair)
            signals = [dict(signal) for signal in proposal.signals]
            if candidate is None:
                session.add(
                    ProductIdentityCandidate(
                        workspace_id=workspace_id,
                        left_product_id=proposal.left_product_id,
                        right_product_id=proposal.right_product_id,
                        match_type=proposal.match_type,
                        score_basis_points=proposal.score_basis_points,
                        signals=signals,
                        algorithm_version=ALGORITHM_VERSION,
                        status="pending",
                    )
                )
                created += 1
                continue
            if candidate.status not in {"pending", "superseded"}:
                continue
            changed = (
                candidate.match_type != proposal.match_type
                or candidate.score_basis_points != proposal.score_basis_points
                or candidate.signals != signals
                or candidate.status != "pending"
            )
            candidate.match_type = proposal.match_type
            candidate.score_basis_points = proposal.score_basis_points
            candidate.signals = signals
            candidate.status = "pending"
            candidate.resolved_by_user_id = None
            candidate.resolved_at = None
            candidate.resolution_reason = None
            if changed:
                updated += 1

        superseded = 0
        if not truncated:
            current_pairs = set(proposals)
            for candidate in existing:
                pair = _pair(candidate.left_product_id, candidate.right_product_id)
                if candidate.status == "pending" and pair not in current_pairs:
                    candidate.status = "superseded"
                    candidate.resolved_at = datetime.now(UTC)
                    candidate.resolution_reason = "No longer produced by the current algorithm"
                    superseded += 1

        await session.flush()
        return CandidateRefreshSummary(
            products_considered=len(products),
            candidates_created=created,
            candidates_updated=updated,
            candidates_superseded=superseded,
            truncated=truncated,
        )

    async def link_products(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
        target_product_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reason: str,
        candidate_id: uuid.UUID | None = None,
    ) -> CommercialProductIdentity:
        if product_id == target_product_id:
            raise CatalogIdentityConflictError("A product cannot be linked to itself")
        products = await self._products_by_ids(
            session,
            workspace_id=workspace_id,
            product_ids=(product_id, target_product_id),
        )
        if set(products) != {product_id, target_product_id}:
            raise CatalogIdentityNotFoundError("One or both products were not found")

        first_membership = await self._active_membership(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
        second_membership = await self._active_membership(
            session,
            workspace_id=workspace_id,
            product_id=target_product_id,
        )

        if (
            first_membership is not None
            and second_membership is not None
            and first_membership.identity_id != second_membership.identity_id
        ):
            raise CatalogIdentityConflictError(
                "Products belong to different identity groups; unlink one group first"
            )

        if first_membership is not None:
            identity = await self._identity_or_error(
                session,
                workspace_id=workspace_id,
                identity_id=first_membership.identity_id,
            )
        elif second_membership is not None:
            identity = await self._identity_or_error(
                session,
                workspace_id=workspace_id,
                identity_id=second_membership.identity_id,
            )
        else:
            identity = CommercialProductIdentity(
                workspace_id=workspace_id,
                status="active",
                created_by_user_id=actor_user_id,
            )
            session.add(identity)
            await session.flush()

        if first_membership is None:
            session.add(
                ProductIdentityMembership(
                    workspace_id=workspace_id,
                    identity_id=identity.id,
                    product_id=product_id,
                    linked_by_user_id=actor_user_id,
                    link_reason=reason,
                )
            )
        if second_membership is None:
            session.add(
                ProductIdentityMembership(
                    workspace_id=workspace_id,
                    identity_id=identity.id,
                    product_id=target_product_id,
                    linked_by_user_id=actor_user_id,
                    link_reason=reason,
                )
            )

        if candidate_id is not None:
            candidate = await self._candidate_or_error(
                session,
                workspace_id=workspace_id,
                candidate_id=candidate_id,
            )
            if _pair(candidate.left_product_id, candidate.right_product_id) != _pair(
                product_id,
                target_product_id,
            ):
                raise CatalogIdentityConflictError(
                    "Identity candidate does not describe the requested product pair"
                )
            if candidate.status not in {"pending", "accepted"}:
                raise CatalogIdentityConflictError(
                    "Only pending identity candidates can be accepted"
                )
            candidate.status = "accepted"
            candidate.resolved_by_user_id = actor_user_id
            candidate.resolved_at = datetime.now(UTC)
            candidate.resolution_reason = reason

        await session.flush()
        return identity

    async def unlink_product(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reason: str,
    ) -> tuple[uuid.UUID, bool]:
        membership = await self._active_membership(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
        if membership is None:
            raise CatalogIdentityNotFoundError("Product is not linked to an identity group")
        identity = await self._identity_or_error(
            session,
            workspace_id=workspace_id,
            identity_id=membership.identity_id,
        )
        now = datetime.now(UTC)
        membership.unlinked_at = now
        membership.unlinked_by_user_id = actor_user_id
        membership.unlink_reason = reason

        remaining = (
            await session.scalars(
                select(ProductIdentityMembership).where(
                    ProductIdentityMembership.workspace_id == workspace_id,
                    ProductIdentityMembership.identity_id == identity.id,
                    ProductIdentityMembership.unlinked_at.is_(None),
                    ProductIdentityMembership.id != membership.id,
                )
            )
        ).all()
        dissolved = len(remaining) < 2
        if dissolved:
            for item in remaining:
                item.unlinked_at = now
                item.unlinked_by_user_id = actor_user_id
                item.unlink_reason = "Identity group dissolved after member unlink"
            identity.status = "dissolved"
            identity.dissolved_at = now

        await session.flush()
        return identity.id, dissolved

    async def reject_candidate(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        candidate_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reason: str,
    ) -> ProductIdentityCandidate:
        candidate = await self._candidate_or_error(
            session,
            workspace_id=workspace_id,
            candidate_id=candidate_id,
        )
        if candidate.status not in {"pending", "rejected"}:
            raise CatalogIdentityConflictError(
                "Only pending identity candidates can be rejected"
            )
        candidate.status = "rejected"
        candidate.resolved_by_user_id = actor_user_id
        candidate.resolved_at = datetime.now(UTC)
        candidate.resolution_reason = reason
        await session.flush()
        return candidate

    async def active_identity_members(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> tuple[
        CommercialProductIdentity,
        list[tuple[ProductIdentityMembership, Product]],
    ]:
        membership = await self._active_membership(
            session,
            workspace_id=workspace_id,
            product_id=product_id,
        )
        if membership is None:
            raise CatalogIdentityNotFoundError("Product is not linked to an identity group")
        identity = await self._identity_or_error(
            session,
            workspace_id=workspace_id,
            identity_id=membership.identity_id,
        )
        rows = (
            await session.execute(
                select(ProductIdentityMembership, Product)
                .join(Product, Product.id == ProductIdentityMembership.product_id)
                .where(
                    ProductIdentityMembership.workspace_id == workspace_id,
                    ProductIdentityMembership.identity_id == identity.id,
                    ProductIdentityMembership.unlinked_at.is_(None),
                    Product.workspace_id == workspace_id,
                    Product.deleted_at.is_(None),
                )
                .order_by(Product.title, Product.id)
            )
        ).all()
        members = [
            (cast(ProductIdentityMembership, row[0]), cast(Product, row[1]))
            for row in rows
        ]
        return identity, members

    async def _profiles(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        products: Sequence[Product],
    ) -> list[_ProductProfile]:
        product_ids = [product.id for product in products]
        if not product_ids:
            return []
        attributes = (
            await session.scalars(
                select(ProductAttribute).where(
                    ProductAttribute.workspace_id == workspace_id,
                    ProductAttribute.product_id.in_(product_ids),
                    ProductAttribute.value_state == "present",
                )
            )
        ).all()
        variants = (
            await session.scalars(
                select(ProductVariant).where(
                    ProductVariant.workspace_id == workspace_id,
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.deleted_at.is_(None),
                )
            )
        ).all()
        attributes_by_product: dict[uuid.UUID, list[ProductAttribute]] = defaultdict(list)
        for attribute in attributes:
            attributes_by_product[attribute.product_id].append(attribute)
        variants_by_product: dict[uuid.UUID, list[ProductVariant]] = defaultdict(list)
        for variant in variants:
            variants_by_product[variant.product_id].append(variant)

        profiles: list[_ProductProfile] = []
        for product in products:
            product_attributes = attributes_by_product[product.id]
            brands = _attribute_identifiers(
                product_attributes,
                {"brand", "vendor", "manufacturer"},
            )
            gtins = _valid_gtins(
                _attribute_identifiers(product_attributes, {"gtin", "barcode"})
            )
            mpns = _bounded_identifiers(
                _attribute_identifiers(product_attributes, {"mpn"}),
                minimum=4,
                maximum=100,
            )
            skus = set(
                _bounded_identifiers(
                    _attribute_identifiers(product_attributes, {"sku"}),
                    minimum=3,
                    maximum=100,
                )
            )
            for variant in variants_by_product[product.id]:
                if variant.sku:
                    normalized_sku = _identifier(variant.sku)
                    if 3 <= len(normalized_sku) <= 100:
                        skus.add(normalized_sku)
            title_key = _title_key(product.title)
            profiles.append(
                _ProductProfile(
                    product=product,
                    title_key=title_key,
                    title_tokens=tuple(_TITLE_TOKEN_PATTERN.findall(title_key)),
                    brands=frozenset(brands),
                    gtins=frozenset(gtins),
                    mpns=frozenset(mpns),
                    skus=frozenset(skus),
                )
            )
        return profiles

    def _proposals(
        self,
        profiles: Sequence[_ProductProfile],
    ) -> dict[tuple[uuid.UUID, uuid.UUID], _CandidateProposal]:
        proposals: dict[tuple[uuid.UUID, uuid.UUID], _CandidateProposal] = {}
        by_gtin: dict[str, list[_ProductProfile]] = defaultdict(list)
        by_mpn_brand: dict[tuple[str, str], list[_ProductProfile]] = defaultdict(list)
        for profile in profiles:
            for gtin in profile.gtins:
                by_gtin[gtin].append(profile)
            for mpn in profile.mpns:
                for brand in profile.brands:
                    by_mpn_brand[(mpn, brand)].append(profile)

        for gtin, group in by_gtin.items():
            self._add_group_pairs(
                proposals,
                group,
                match_type="deterministic",
                score_basis_points=10000,
                signals=(
                    {
                        "kind": "gtin_exact",
                        "value": gtin,
                        "weight_basis_points": 10000,
                    },
                ),
            )
        for (mpn, brand), group in by_mpn_brand.items():
            self._add_group_pairs(
                proposals,
                group,
                match_type="deterministic",
                score_basis_points=9800,
                signals=(
                    {
                        "kind": "mpn_exact",
                        "value": mpn,
                        "weight_basis_points": 8000,
                    },
                    {
                        "kind": "brand_exact",
                        "value": brand,
                        "weight_basis_points": 1800,
                    },
                ),
            )

        fuzzy_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
        blocks: dict[str, list[_ProductProfile]] = defaultdict(list)
        for profile in profiles:
            leading = profile.title_tokens[0] if profile.title_tokens else ""
            if not leading:
                continue
            if profile.brands:
                for brand in profile.brands:
                    blocks[f"brand:{brand}:{leading}"].append(profile)
            else:
                second = profile.title_tokens[1] if len(profile.title_tokens) > 1 else ""
                blocks[f"title:{leading}:{second}"].append(profile)
        for group in blocks.values():
            if len(group) > _MAX_BLOCK_SIZE:
                continue
            for left, right in combinations(group, 2):
                fuzzy_pairs.add(_pair(left.product.id, right.product.id))

        profile_by_id = {profile.product.id: profile for profile in profiles}
        for pair in fuzzy_pairs:
            if pair in proposals:
                continue
            left = profile_by_id[pair[0]]
            right = profile_by_id[pair[1]]
            proposal = _fuzzy_proposal(left, right)
            if proposal is not None:
                proposals[pair] = proposal
        return proposals

    def _add_group_pairs(
        self,
        proposals: dict[tuple[uuid.UUID, uuid.UUID], _CandidateProposal],
        group: Sequence[_ProductProfile],
        *,
        match_type: str,
        score_basis_points: int,
        signals: tuple[dict[str, object], ...],
    ) -> None:
        if len(group) > _MAX_BLOCK_SIZE:
            return
        for left, right in combinations(group, 2):
            pair = _pair(left.product.id, right.product.id)
            current = proposals.get(pair)
            if current is not None and current.score_basis_points >= score_basis_points:
                continue
            proposals[pair] = _CandidateProposal(
                left_product_id=pair[0],
                right_product_id=pair[1],
                match_type=match_type,
                score_basis_points=score_basis_points,
                signals=signals,
            )

    async def _products_by_ids(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, Product]:
        ids = tuple(product_ids)
        products = (
            await session.scalars(
                select(Product).where(
                    Product.workspace_id == workspace_id,
                    Product.id.in_(ids),
                    Product.deleted_at.is_(None),
                    Product.status == "active",
                )
            )
        ).all()
        return {product.id: product for product in products}

    async def _active_membership(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> ProductIdentityMembership | None:
        return await session.scalar(
            select(ProductIdentityMembership).where(
                ProductIdentityMembership.workspace_id == workspace_id,
                ProductIdentityMembership.product_id == product_id,
                ProductIdentityMembership.unlinked_at.is_(None),
            )
        )

    async def _identity_or_error(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        identity_id: uuid.UUID,
    ) -> CommercialProductIdentity:
        identity = await session.scalar(
            select(CommercialProductIdentity).where(
                CommercialProductIdentity.workspace_id == workspace_id,
                CommercialProductIdentity.id == identity_id,
                CommercialProductIdentity.status == "active",
            )
        )
        if identity is None:
            raise CatalogIdentityNotFoundError("Identity group was not found")
        return identity

    async def _candidate_or_error(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        candidate_id: uuid.UUID,
    ) -> ProductIdentityCandidate:
        candidate = await session.scalar(
            select(ProductIdentityCandidate).where(
                ProductIdentityCandidate.workspace_id == workspace_id,
                ProductIdentityCandidate.id == candidate_id,
            )
        )
        if candidate is None:
            raise CatalogIdentityNotFoundError("Identity candidate was not found")
        return candidate


def _fuzzy_proposal(
    left: _ProductProfile,
    right: _ProductProfile,
) -> _CandidateProposal | None:
    title_ratio = SequenceMatcher(None, left.title_key, right.title_key).ratio()
    shared_brands = left.brands & right.brands
    shared_skus = left.skus & right.skus
    if title_ratio < 0.82 or not (shared_brands or shared_skus):
        return None

    signals: list[dict[str, object]] = [
        {
            "kind": "title_similarity",
            "value": f"{title_ratio:.4f}",
            "weight_basis_points": round(title_ratio * 8500),
        }
    ]
    score = round(title_ratio * 8500)
    if shared_brands:
        brand = sorted(shared_brands)[0]
        signals.append(
            {
                "kind": "brand_exact",
                "value": brand,
                "weight_basis_points": 1000,
            }
        )
        score += 1000
    if shared_skus:
        sku = sorted(shared_skus)[0]
        signals.append(
            {
                "kind": "sku_exact_non_unique",
                "value": sku,
                "weight_basis_points": 500,
            }
        )
        score += 500
    score = min(score, 9700)
    if score < 8500:
        return None
    pair = _pair(left.product.id, right.product.id)
    return _CandidateProposal(
        left_product_id=pair[0],
        right_product_id=pair[1],
        match_type="fuzzy",
        score_basis_points=score,
        signals=tuple(signals),
    )


def _attribute_identifiers(
    attributes: Sequence[ProductAttribute],
    keys: set[str],
) -> set[str]:
    values: set[str] = set()
    for attribute in attributes:
        if attribute.key not in keys:
            continue
        for value in _string_values(attribute.value):
            normalized = _identifier(value)
            if normalized:
                values.add(normalized)
    return values


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("canonical", "raw", "value"):
            item = value.get(key)
            if isinstance(item, str) and item not in result:
                result.append(item)
        return tuple(result)
    return ()


def _valid_gtins(values: Iterable[str]) -> set[str]:
    return {value for value in values if value.isdigit() and len(value) in {8, 12, 13, 14}}


def _bounded_identifiers(
    values: Iterable[str],
    *,
    minimum: int,
    maximum: int,
) -> set[str]:
    return {value for value in values if minimum <= len(value) <= maximum}


def _identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _IDENTIFIER_PATTERN.sub("", normalized)


def _title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(_TITLE_TOKEN_PATTERN.findall(normalized))


def _pair(left: uuid.UUID, right: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (left, right) if left.hex < right.hex else (right, left)
