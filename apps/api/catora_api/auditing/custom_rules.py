from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing import rules as audit_rules
from catora_api.auditing.types import ProductAuditSnapshot, RuleEvaluation, Severity
from catora_api.db.models.audit import AuditRun, RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField

CUSTOM_RELATIONAL_RULE_TYPE = "workspace_relational_constraint"
AUDIT_RULE_TYPES = (
    "taxonomy_field_requirement",
    CUSTOM_RELATIONAL_RULE_TYPE,
)
CUSTOM_RULE_KEY_PREFIX = "custom."
type RelationshipOperator = Literal[
    "less_than_or_equal_to_field",
    "greater_than_or_equal_to_field",
    "matches_product_field",
]
_RELATIONSHIP_OPERATORS: frozenset[str] = frozenset(
    {
        "less_than_or_equal_to_field",
        "greater_than_or_equal_to_field",
        "matches_product_field",
    }
)
_NUMERIC_TYPES = frozenset({"integer", "decimal"})


class CustomAuditRuleConflictError(ValueError):
    pass


class CustomAuditRuleReferenceError(ValueError):
    pass


class CustomAuditRuleConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FieldContract:
    specification: dict[str, object]
    scope: str
    data_type: str
    canonical_unit: str | None


@dataclass(frozen=True, slots=True)
class CustomAuditRuleRecord:
    definition: RuleDefinition
    version: RuleVersion
    rule: audit_rules.TaxonomyFieldRule
    relationship: RelationshipOperator
    related_field_key: str


@dataclass(frozen=True, slots=True)
class AuditRuleSet:
    field_rules: tuple[audit_rules.TaxonomyFieldRule, ...]
    custom_relationship_rules: tuple[audit_rules.TaxonomyFieldRule, ...]


class CustomAuditRuleService:
    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        key: str,
        name: str,
        description: str,
        taxonomy_version: str,
        category_key: str,
        field_key: str,
        relationship: RelationshipOperator,
        related_field_key: str,
        severity: Severity,
    ) -> CustomAuditRuleRecord:
        definition_key = f"{CUSTOM_RULE_KEY_PREFIX}{key}"
        definition = await session.scalar(
            select(RuleDefinition).where(
                RuleDefinition.workspace_id == workspace_id,
                RuleDefinition.key == definition_key,
            )
        )
        if definition is None:
            definition = RuleDefinition(
                workspace_id=workspace_id,
                key=definition_key,
                name=name,
                rule_type=CUSTOM_RELATIONAL_RULE_TYPE,
                description=description,
            )
            session.add(definition)
            await session.flush()
        elif (
            definition.rule_type != CUSTOM_RELATIONAL_RULE_TYPE
            or definition.name != name
            or definition.description != description
        ):
            raise CustomAuditRuleConflictError(
                f"Rule key {definition_key!r} already exists with a different definition"
            )

        existing_version = await session.scalar(
            select(RuleVersion.id).where(
                RuleVersion.rule_definition_id == definition.id,
                RuleVersion.version == taxonomy_version,
            )
        )
        if existing_version is not None:
            raise CustomAuditRuleConflictError(
                f"Rule {definition_key!r}@{taxonomy_version} already exists"
            )

        field_contracts = await _load_field_contracts(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
            category_key=category_key,
            field_keys={field_key, related_field_key},
        )
        specification = build_custom_rule_specification(
            category_key=category_key,
            field_key=field_key,
            relationship=relationship,
            related_field_key=related_field_key,
            severity=severity,
            field_specification=field_contracts[field_key].specification,
            related_field_specification=field_contracts[related_field_key].specification,
        )
        version = RuleVersion(
            workspace_id=workspace_id,
            rule_definition_id=definition.id,
            version=taxonomy_version,
            specification=specification,
            is_immutable=True,
        )
        session.add(version)
        await session.flush()
        return _record(definition, version)

    async def list(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
    ) -> tuple[CustomAuditRuleRecord, ...]:
        rows = (
            await session.execute(
                select(RuleDefinition, RuleVersion)
                .join(
                    RuleVersion,
                    RuleVersion.rule_definition_id == RuleDefinition.id,
                )
                .where(
                    RuleDefinition.workspace_id == workspace_id,
                    RuleDefinition.rule_type == CUSTOM_RELATIONAL_RULE_TYPE,
                    RuleVersion.workspace_id == workspace_id,
                    RuleVersion.is_immutable.is_(True),
                )
                .order_by(RuleDefinition.key, RuleVersion.version)
            )
        ).all()
        return tuple(_record(definition, version) for definition, version in rows)


async def current_audit_rule_version_ids(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
) -> list[uuid.UUID]:
    return list(
        (
            await session.scalars(
                select(RuleVersion.id)
                .join(
                    RuleDefinition,
                    RuleDefinition.id == RuleVersion.rule_definition_id,
                )
                .where(
                    RuleVersion.workspace_id == workspace_id,
                    RuleDefinition.workspace_id == workspace_id,
                    RuleVersion.version == taxonomy_version,
                    RuleVersion.is_immutable.is_(True),
                    RuleDefinition.rule_type.in_(AUDIT_RULE_TYPES),
                )
                .order_by(RuleDefinition.key)
            )
        ).all()
    )


async def load_audit_rule_set(
    session: AsyncSession,
    run: AuditRun,
) -> AuditRuleSet:
    rule_ids = [uuid.UUID(value) for value in run.rule_version_set]
    rows = (
        await session.execute(
            select(RuleVersion, RuleDefinition)
            .join(
                RuleDefinition,
                RuleDefinition.id == RuleVersion.rule_definition_id,
            )
            .where(
                RuleVersion.workspace_id == run.workspace_id,
                RuleDefinition.workspace_id == run.workspace_id,
                RuleVersion.id.in_(rule_ids),
                RuleVersion.version == run.taxonomy_version,
                RuleVersion.is_immutable.is_(True),
                RuleDefinition.rule_type.in_(AUDIT_RULE_TYPES),
            )
            .order_by(RuleDefinition.key)
        )
    ).all()
    if len(rows) != len(rule_ids):
        raise CustomAuditRuleConfigurationError(
            "Audit rule version set is missing, mutable or unsupported"
        )

    field_rules: list[audit_rules.TaxonomyFieldRule] = []
    custom_rules: list[audit_rules.TaxonomyFieldRule] = []
    for version, definition in rows:
        rule = audit_rules.TaxonomyFieldRule.from_specification(
            rule_version_id=version.id,
            rule_key=definition.key,
            rule_version=version.version,
            specification=version.specification,
        )
        if definition.rule_type == CUSTOM_RELATIONAL_RULE_TYPE:
            if not rule.has_relationship_constraints:
                raise CustomAuditRuleConfigurationError(
                    f"Custom rule {definition.key!r} has no supported relationship constraint"
                )
            custom_rules.append(rule)
        else:
            field_rules.append(rule)
    return AuditRuleSet(
        field_rules=tuple(field_rules),
        custom_relationship_rules=tuple(custom_rules),
    )


def evaluate_custom_relationship_rules(
    snapshot: ProductAuditSnapshot,
    rules: tuple[audit_rules.TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    return tuple(
        evaluation
        for rule in rules
        if rule.category_key == snapshot.category_key
        for evaluation in audit_rules._evaluate_relationships(snapshot, rule)
    )


def build_custom_rule_specification(
    *,
    category_key: str,
    field_key: str,
    relationship: RelationshipOperator,
    related_field_key: str,
    severity: Severity,
    field_specification: Mapping[str, object],
    related_field_specification: Mapping[str, object],
) -> dict[str, object]:
    field = _field_contract(
        field_specification,
        category_key=category_key,
        field_key=field_key,
    )
    related = _field_contract(
        related_field_specification,
        category_key=category_key,
        field_key=related_field_key,
    )
    _validate_reference_contract(
        field=field,
        related=related,
        relationship=relationship,
        field_key=field_key,
        related_field_key=related_field_key,
    )

    field_payload = dict(field.specification)
    constraints = dict(_mapping(field_payload.get("constraints")))
    for operator in _RELATIONSHIP_OPERATORS:
        constraints.pop(operator, None)
    constraints[relationship] = related_field_key
    field_payload["constraints"] = constraints
    specification: dict[str, object] = {
        "category_key": category_key,
        "field_key": field_key,
        "requirement": "recommended",
        "severity": severity,
        "field": field_payload,
        "custom_rule": {
            "relationship": relationship,
            "related_field_key": related_field_key,
        },
    }
    try:
        audit_rules.TaxonomyFieldRule.from_specification(
            rule_version_id=uuid.uuid4(),
            rule_key=f"{CUSTOM_RULE_KEY_PREFIX}validation",
            rule_version="validation",
            specification=specification,
        )
    except audit_rules.RuleSpecificationError as exc:
        raise CustomAuditRuleReferenceError(str(exc)) from exc
    return specification


def custom_rule_metadata(
    specification: Mapping[str, object],
) -> tuple[RelationshipOperator, str]:
    custom_rule = _required_mapping(specification, "custom_rule")
    relationship_value = _required_str(custom_rule, "relationship")
    if relationship_value not in _RELATIONSHIP_OPERATORS:
        raise CustomAuditRuleConfigurationError(
            f"Unsupported custom relationship {relationship_value!r}"
        )
    related_field_key = _required_str(custom_rule, "related_field_key")
    return cast(RelationshipOperator, relationship_value), related_field_key


async def _load_field_contracts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
    category_key: str,
    field_keys: set[str],
) -> dict[str, FieldContract]:
    rows = (
        await session.execute(
            select(TaxonomyField, Category)
            .join(Category, Category.id == TaxonomyField.category_id)
            .where(
                TaxonomyField.workspace_id == workspace_id,
                TaxonomyField.version == taxonomy_version,
                TaxonomyField.key.in_(sorted(field_keys)),
                TaxonomyField.is_immutable.is_(True),
                Category.workspace_id == workspace_id,
                Category.taxonomy_version == taxonomy_version,
                Category.key == category_key,
                Category.is_immutable.is_(True),
            )
        )
    ).all()
    by_key = {
        field.key: _field_contract(
            field.specification,
            category_key=category.key,
            field_key=field.key,
        )
        for field, category in rows
    }
    missing = field_keys - set(by_key)
    if missing:
        raise CustomAuditRuleReferenceError(
            "Custom rule references unknown immutable taxonomy fields: "
            + ", ".join(sorted(missing))
        )
    return by_key


def _field_contract(
    specification: Mapping[str, object],
    *,
    category_key: str,
    field_key: str,
) -> FieldContract:
    if _required_str(specification, "category_key") != category_key:
        raise CustomAuditRuleReferenceError("Field category does not match the requested category")
    if _required_str(specification, "key") != field_key:
        raise CustomAuditRuleReferenceError("Field key does not match the requested field")
    return FieldContract(
        specification=dict(specification),
        scope=_required_str(specification, "scope"),
        data_type=_required_str(specification, "data_type"),
        canonical_unit=_optional_str(specification.get("canonical_unit")),
    )


def _validate_reference_contract(
    *,
    field: FieldContract,
    related: FieldContract,
    relationship: RelationshipOperator,
    field_key: str,
    related_field_key: str,
) -> None:
    if relationship not in _RELATIONSHIP_OPERATORS:
        raise CustomAuditRuleReferenceError(f"Unsupported relationship {relationship!r}")
    if relationship in {
        "less_than_or_equal_to_field",
        "greater_than_or_equal_to_field",
    }:
        if field_key == related_field_key:
            raise CustomAuditRuleReferenceError(
                "Numeric relationships cannot reference their own field"
            )
        if field.data_type not in _NUMERIC_TYPES or related.data_type not in _NUMERIC_TYPES:
            raise CustomAuditRuleReferenceError(
                "Numeric relationships require two integer or decimal fields"
            )
        if not _scope_supports_same_context(field.scope, related.scope):
            raise CustomAuditRuleReferenceError(
                "Related field scope does not cover every evaluated field scope"
            )
        if field.canonical_unit != related.canonical_unit:
            raise CustomAuditRuleReferenceError(
                "Numeric relationship fields must use the same canonical unit"
            )
        return

    if field.scope not in {"variant", "both"}:
        raise CustomAuditRuleReferenceError(
            "matches_product_field requires a variant or both-scope field"
        )
    if (
        related_field_key != field_key
        and related.scope not in {"product", "both"}
    ):
        raise CustomAuditRuleReferenceError(
            "matches_product_field must reference a product or both-scope field"
        )
    if field.data_type != related.data_type:
        raise CustomAuditRuleReferenceError(
            "Product and variant match fields must use the same data type"
        )
    if field.canonical_unit != related.canonical_unit:
        raise CustomAuditRuleReferenceError(
            "Product and variant match fields must use the same canonical unit"
        )


def _scope_supports_same_context(field_scope: str, related_scope: str) -> bool:
    if field_scope == "product":
        return related_scope in {"product", "both"}
    if field_scope == "variant":
        return related_scope in {"variant", "both"}
    if field_scope == "both":
        return related_scope == "both"
    return False


def _record(
    definition: RuleDefinition,
    version: RuleVersion,
) -> CustomAuditRuleRecord:
    rule = audit_rules.TaxonomyFieldRule.from_specification(
        rule_version_id=version.id,
        rule_key=definition.key,
        rule_version=version.version,
        specification=version.specification,
    )
    relationship, related_field_key = custom_rule_metadata(version.specification)
    return CustomAuditRuleRecord(
        definition=definition,
        version=version,
        rule=rule,
        relationship=relationship,
        related_field_key=related_field_key,
    )


def _required_mapping(
    mapping: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise CustomAuditRuleConfigurationError(f"{key!r} must be an object")
    return cast(Mapping[str, object], value)


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _required_str(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise CustomAuditRuleConfigurationError(f"{key!r} must be a non-empty string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
