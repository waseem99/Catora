from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._content_quality import (
    CONTENT_QUALITY_ALGORITHM_VERSION,
    CONTENT_RULE_TEMPLATES,
    ContentRuleConfigurationError,
    ContentRuleTemplate,
    content_rule_keys,
    evaluate_content_quality_rule,
    is_content_quality_rule,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category

__all__ = [
    "CONTENT_QUALITY_ALGORITHM_VERSION",
    "CONTENT_RULE_TEMPLATES",
    "ContentRuleConfigurationError",
    "ContentRuleTemplate",
    "content_rule_keys",
    "ensure_standard_content_rules",
    "evaluate_content_quality_rule",
    "is_content_quality_rule",
]


async def ensure_standard_content_rules(
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
        raise ContentRuleConfigurationError(
            f"No immutable taxonomy categories exist for version {taxonomy_version}"
        )
    for category in categories:
        for template in CONTENT_RULE_TEMPLATES:
            await _ensure_rule(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
                category=category,
                template=template,
            )


async def _ensure_rule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
    category: Category,
    template: ContentRuleTemplate,
) -> None:
    rule_key = f"builtin.{category.key}.{template.suffix}"
    name = f"{category.label}: {template.label}"
    description = (
        f"Checks deterministic {template.label} for category {category.key}."
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
            rule_type="taxonomy_field_requirement",
            description=description,
        )
        session.add(definition)
        await session.flush()
    elif (
        definition.name != name
        or definition.rule_type != "taxonomy_field_requirement"
        or definition.description != description
    ):
        raise ContentRuleConfigurationError(
            f"Standard content rule definition {rule_key!r} has immutable drift"
        )

    expected = _specification(
        category_key=category.key,
        taxonomy_version=taxonomy_version,
        template=template,
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
        raise ContentRuleConfigurationError(
            f"Standard content rule {rule_key!r}@{taxonomy_version} has immutable drift"
        )


def _specification(
    *,
    category_key: str,
    taxonomy_version: str,
    template: ContentRuleTemplate,
) -> dict[str, object]:
    return {
        "category_key": category_key,
        "field_key": template.field_key,
        "requirement": "recommended",
        "severity": template.severity,
        "field": {
            "category_key": category_key,
            "key": template.field_key,
            "label": template.field_key.replace("_", " ").title(),
            "scope": "product",
            "data_type": "string",
            "canonical_unit": None,
            "allowed_values": [],
            "markets": [],
            "constraints": dict(template.constraints),
            "mapping": {},
            "taxonomy_version": taxonomy_version,
            "content_quality_algorithm_version": CONTENT_QUALITY_ALGORITHM_VERSION,
        },
    }


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
