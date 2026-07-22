from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._duplicate_quality import (
    DUPLICATE_CONTENT_ALGORITHM_VERSION,
    DuplicateContentRuleConfigurationError,
    evaluate_duplicate_content_rule,
    is_duplicate_content_rule,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category

DUPLICATE_RULE_SUFFIX = "duplicate_content"
DUPLICATE_RULE_TYPE = "taxonomy_field_requirement"

__all__ = [
    "DUPLICATE_CONTENT_ALGORITHM_VERSION",
    "DUPLICATE_RULE_SUFFIX",
    "DuplicateContentRuleConfigurationError",
    "duplicate_rule_key",
    "ensure_standard_duplicate_content_rules",
    "evaluate_duplicate_content_rule",
    "is_duplicate_content_rule",
]


async def ensure_standard_duplicate_content_rules(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
) -> None:
    categories = (
        await session.scalars(
            select(Category)
            .where(
                Category.workspace_id == workspace_id,
                Category.taxonomy_version == taxonomy_version,
                Category.is_immutable.is_(True),
            )
            .order_by(Category.key)
        )
    ).all()
    if not categories:
        raise DuplicateContentRuleConfigurationError(
            f"No immutable taxonomy categories exist for version {taxonomy_version}"
        )
    for category in categories:
        await _ensure_rule(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
            category=category,
        )


async def _ensure_rule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
    category: Category,
) -> None:
    rule_key = duplicate_rule_key(category.key)
    name = f"{category.label}: duplicate content"
    description = (
        f"Checks exact and conservative near-duplicate title and description content "
        f"within category {category.key}."
    )
    definition = await session.scalar(
        select(RuleDefinition).where(
            RuleDefinition.workspace_id == workspace_id,
            RuleDefinition.key == rule_key,
        )
    )
    if definition is None:
        definition = RuleDefinition(
            workspace_id=workspace_id,
            key=rule_key,
            name=name,
            rule_type=DUPLICATE_RULE_TYPE,
            description=description,
        )
        session.add(definition)
        await session.flush()
    elif (
        definition.name != name
        or definition.rule_type != DUPLICATE_RULE_TYPE
        or definition.description != description
    ):
        raise DuplicateContentRuleConfigurationError(
            f"Standard duplicate-content rule definition {rule_key!r} has immutable drift"
        )

    expected = _specification(
        category_key=category.key,
        taxonomy_version=taxonomy_version,
    )
    version = await session.scalar(
        select(RuleVersion).where(
            RuleVersion.rule_definition_id == definition.id,
            RuleVersion.version == taxonomy_version,
        )
    )
    if version is None:
        session.add(
            RuleVersion(
                workspace_id=workspace_id,
                rule_definition_id=definition.id,
                version=taxonomy_version,
                specification=expected,
                is_immutable=True,
            )
        )
        await session.flush()
    elif (
        not version.is_immutable
        or _canonical_json(version.specification) != _canonical_json(expected)
    ):
        raise DuplicateContentRuleConfigurationError(
            f"Standard duplicate-content rule {rule_key!r}@{taxonomy_version} has immutable drift"
        )


def _specification(*, category_key: str, taxonomy_version: str) -> dict[str, object]:
    return {
        "category_key": category_key,
        "field_key": "duplicate_content",
        "requirement": "recommended",
        "severity": "medium",
        "field": {
            "category_key": category_key,
            "key": "duplicate_content",
            "label": "Duplicate content",
            "scope": "product",
            "data_type": "object",
            "canonical_unit": None,
            "allowed_values": [],
            "markets": [],
            "constraints": {
                "duplicate_content_kind": "catalog_similarity",
                "simhash_bits": 64,
                "simhash_max_distance": 3,
                "title_minimum_characters": 16,
                "title_minimum_unique_tokens": 4,
                "title_jaccard_basis_points": 7500,
                "description_minimum_characters": 80,
                "description_minimum_unique_tokens": 12,
                "description_jaccard_basis_points": 8500,
                "maximum_peer_samples": 20,
            },
            "mapping": {},
            "taxonomy_version": taxonomy_version,
            "duplicate_content_algorithm_version": DUPLICATE_CONTENT_ALGORITHM_VERSION,
        },
    }


def duplicate_rule_key(category_key: str) -> str:
    return f"builtin.{category_key}.{DUPLICATE_RULE_SUFFIX}"


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
