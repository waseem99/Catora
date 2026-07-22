from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._image_quality import (
    IMAGE_QUALITY_ALGORITHM_VERSION,
    ImageRuleConfigurationError,
    evaluate_image_quality_rule,
    is_image_quality_rule,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category

IMAGE_RULE_SUFFIX = "image_quality"
IMAGE_RULE_TYPE = "taxonomy_field_requirement"

__all__ = [
    "IMAGE_QUALITY_ALGORITHM_VERSION",
    "IMAGE_RULE_SUFFIX",
    "ImageRuleConfigurationError",
    "ensure_standard_image_rules",
    "evaluate_image_quality_rule",
    "image_rule_keys",
    "is_image_quality_rule",
]


async def ensure_standard_image_rules(
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
        raise ImageRuleConfigurationError(
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
    rule_key = f"builtin.{category.key}.{IMAGE_RULE_SUFFIX}"
    name = f"{category.label}: image and alt-text quality"
    description = (
        f"Checks deterministic image inventory and alt-text quality for category {category.key}."
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
            rule_type=IMAGE_RULE_TYPE,
            description=description,
        )
        session.add(definition)
        await session.flush()
    elif (
        definition.name != name
        or definition.rule_type != IMAGE_RULE_TYPE
        or definition.description != description
    ):
        raise ImageRuleConfigurationError(
            f"Standard image rule definition {rule_key!r} has immutable drift"
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
        raise ImageRuleConfigurationError(
            f"Standard image rule {rule_key!r}@{taxonomy_version} has immutable drift"
        )


def _specification(
    *,
    category_key: str,
    taxonomy_version: str,
) -> dict[str, object]:
    return {
        "category_key": category_key,
        "field_key": "images",
        "requirement": "recommended",
        "severity": "medium",
        "field": {
            "category_key": category_key,
            "key": "images",
            "label": "Images",
            "scope": "product",
            "data_type": "list",
            "canonical_unit": None,
            "allowed_values": [],
            "markets": [],
            "constraints": {
                "image_quality_kind": "inventory_alt_text",
                "min_image_count": 1,
                "require_alt_text": True,
                "min_alt_length": 5,
                "max_alt_length": 300,
            },
            "mapping": {},
            "taxonomy_version": taxonomy_version,
            "image_quality_algorithm_version": IMAGE_QUALITY_ALGORITHM_VERSION,
        },
    }


def image_rule_keys(categories: list[str]) -> tuple[str, ...]:
    return tuple(
        f"builtin.{category_key}.{IMAGE_RULE_SUFFIX}"
        for category_key in sorted(categories)
    )


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
