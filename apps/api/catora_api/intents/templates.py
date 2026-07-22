from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from catora_api.intents.types import IntentConstraint, SoftPreference, StructuredBuyerIntent
from catora_api.taxonomy.loader import load_bundled_taxonomy

TEMPLATE_TAXONOMY_VERSION = "1.0.0"
TemplateVersion = Literal[1]


class BuyerIntentTemplateContractError(ValueError):
    pass


class BuyerIntentTemplateNotFoundError(LookupError):
    pass


class BuyerIntentTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=150)
    version: TemplateVersion = 1
    taxonomy_version: str = TEMPLATE_TAXONOMY_VERSION
    name: str = Field(min_length=1, max_length=250)
    summary: str = Field(min_length=1, max_length=500)
    use_cases: tuple[str, ...] = Field(min_length=1, max_length=20)
    structured_intent: StructuredBuyerIntent

    @field_validator("name", "summary")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("template text must not be blank")
        return normalized

    @field_validator("use_cases")
    @classmethod
    def normalize_use_cases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if any(not item for item in normalized):
            raise ValueError("template use cases must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("template use cases must be unique")
        if any(not item.replace("_", "").isalnum() for item in normalized):
            raise ValueError("template use cases must be canonical keys")
        return normalized

    @model_validator(mode="after")
    def validate_version(self) -> Self:
        if self.taxonomy_version != TEMPLATE_TAXONOMY_VERSION:
            raise ValueError("template taxonomy version must match the bundled contract")
        return self


@dataclass(frozen=True, slots=True)
class BuyerIntentTemplatePage:
    items: tuple[BuyerIntentTemplate, ...]
    total: int


def _template(
    *,
    key: str,
    name: str,
    summary: str,
    use_cases: tuple[str, ...],
    query: str,
    category_keys: tuple[str, ...],
    hard_constraints: tuple[IntentConstraint, ...],
    soft_preferences: tuple[SoftPreference, ...] = (),
) -> BuyerIntentTemplate:
    return BuyerIntentTemplate(
        key=key,
        name=name,
        summary=summary,
        use_cases=use_cases,
        structured_intent=StructuredBuyerIntent(
            query=query,
            category_keys=category_keys,
            hard_constraints=hard_constraints,
            soft_preferences=soft_preferences,
        ),
    )


def _build_templates() -> tuple[BuyerIntentTemplate, ...]:
    return (
        _template(
            key="accessible_adjustable_workspace",
            name="Accessible adjustable workspace",
            summary="Adjustable office furniture with bounded dimensions for a flexible workspace.",
            use_cases=("accessibility", "commercial_use", "room_planning"),
            query=(
                "An adjustable desk or office workstation no wider than 140 cm and at least "
                "60 cm deep"
            ),
            category_keys=("desks_office_furniture",),
            hard_constraints=(
                IntentConstraint(field_key="adjustable", operator="equals", expected=True),
                IntentConstraint(
                    field_key="width_mm",
                    operator="less_than_or_equal",
                    expected=1400,
                    unit="mm",
                ),
                IntentConstraint(
                    field_key="depth_mm",
                    operator="greater_than_or_equal",
                    expected=600,
                    unit="mm",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="load_capacity_kg",
                        operator="greater_than_or_equal",
                        expected=50,
                        unit="kg",
                    ),
                    weight=35,
                ),
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="warranty_months",
                        operator="greater_than_or_equal",
                        expected=24,
                        unit="month",
                    ),
                    weight=20,
                ),
            ),
        ),
        _template(
            key="apartment_delivery_bed",
            name="Apartment-delivery bed",
            summary="A bed sized for constrained delivery access with a common mattress option.",
            use_cases=("apartment_delivery", "door_access", "delivery_planning"),
            query="A double, full, or queen bed whose packaged width is no more than 85 cm",
            category_keys=("beds_mattresses",),
            hard_constraints=(
                IntentConstraint(
                    field_key="package_width_mm",
                    operator="less_than_or_equal",
                    expected=850,
                    unit="mm",
                ),
                IntentConstraint(
                    field_key="mattress_size",
                    operator="one_of",
                    expected=("double", "full", "queen"),
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="assembly_required",
                        operator="equals",
                        expected=True,
                    ),
                    weight=15,
                ),
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="warranty_months",
                        operator="greater_than_or_equal",
                        expected=24,
                        unit="month",
                    ),
                    weight=20,
                ),
            ),
        ),
        _template(
            key="compact_space_sofa",
            name="Compact-space sofa",
            summary="A three-seat sofa bounded for smaller living rooms and apartments.",
            use_cases=("compact_spaces", "family_use", "room_planning"),
            query="A sofa for at least three people, no wider than 210 cm and no deeper than 95 cm",
            category_keys=("sofas_sectionals",),
            hard_constraints=(
                IntentConstraint(
                    field_key="seating_capacity",
                    operator="greater_than_or_equal",
                    expected=3,
                ),
                IntentConstraint(
                    field_key="width_mm",
                    operator="less_than_or_equal",
                    expected=2100,
                    unit="mm",
                ),
                IntentConstraint(
                    field_key="depth_mm",
                    operator="less_than_or_equal",
                    expected=950,
                    unit="mm",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="care_instructions",
                        operator="contains",
                        expected="clean",
                    ),
                    weight=30,
                ),
            ),
        ),
        _template(
            key="easy_care_dining_for_six",
            name="Easy-care dining for six",
            summary=(
                "A dining table or set with six-person capacity and explicit easy-care "
                "guidance."
            ),
            use_cases=("easy_care", "family_use", "entertaining"),
            query="An easy-care dining table or dining set that seats at least six people",
            category_keys=("dining_tables_chairs",),
            hard_constraints=(
                IntentConstraint(
                    field_key="seating_capacity",
                    operator="greater_than_or_equal",
                    expected=6,
                ),
                IntentConstraint(
                    field_key="care_instructions",
                    operator="contains",
                    expected="clean",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="assembly_required",
                        operator="equals",
                        expected=False,
                    ),
                    weight=25,
                ),
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="warranty_months",
                        operator="greater_than_or_equal",
                        expected=24,
                        unit="month",
                    ),
                    weight=20,
                ),
            ),
        ),
        _template(
            key="family_friendly_sofa",
            name="Family-friendly sofa",
            summary="A high-capacity sofa with a documented load rating and care information.",
            use_cases=("family_use", "durability", "easy_care"),
            query=(
                "A family sofa for at least four people with a load capacity of at least 300 kg"
            ),
            category_keys=("sofas_sectionals",),
            hard_constraints=(
                IntentConstraint(
                    field_key="seating_capacity",
                    operator="greater_than_or_equal",
                    expected=4,
                ),
                IntentConstraint(
                    field_key="load_capacity_kg",
                    operator="greater_than_or_equal",
                    expected=300,
                    unit="kg",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="care_instructions",
                        operator="contains",
                        expected="clean",
                    ),
                    weight=35,
                ),
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="warranty_months",
                        operator="greater_than_or_equal",
                        expected=36,
                        unit="month",
                    ),
                    weight=20,
                ),
            ),
        ),
        _template(
            key="low_assembly_storage",
            name="Low-assembly compact storage",
            summary=(
                "Compact storage furniture that arrives assembled and fits a shallow "
                "footprint."
            ),
            use_cases=("low_assembly", "compact_spaces", "room_planning"),
            query=(
                "A storage cabinet that requires no assembly, is no wider than 120 cm, and is "
                "no deeper than 50 cm"
            ),
            category_keys=("storage_cabinets",),
            hard_constraints=(
                IntentConstraint(
                    field_key="assembly_required",
                    operator="equals",
                    expected=False,
                ),
                IntentConstraint(
                    field_key="width_mm",
                    operator="less_than_or_equal",
                    expected=1200,
                    unit="mm",
                ),
                IntentConstraint(
                    field_key="depth_mm",
                    operator="less_than_or_equal",
                    expected=500,
                    unit="mm",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="weight_g",
                        operator="less_than_or_equal",
                        expected=50_000,
                        unit="g",
                    ),
                    weight=25,
                ),
            ),
        ),
        _template(
            key="weather_ready_outdoor_seating",
            name="Weather-ready outdoor seating",
            summary="Outdoor seating for four or more people with explicit care guidance.",
            use_cases=("outdoor_use", "weather_resistance", "family_use"),
            query=(
                "Outdoor seating for at least four people with documented outdoor care "
                "instructions"
            ),
            category_keys=("outdoor_furniture",),
            hard_constraints=(
                IntentConstraint(
                    field_key="usage_environment",
                    operator="one_of",
                    expected=("outdoor", "indoor_outdoor"),
                ),
                IntentConstraint(
                    field_key="seating_capacity",
                    operator="greater_than_or_equal",
                    expected=4,
                ),
                IntentConstraint(
                    field_key="care_instructions",
                    operator="contains",
                    expected="outdoor",
                ),
            ),
            soft_preferences=(
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="materials",
                        operator="contains",
                        expected="aluminium",
                    ),
                    weight=25,
                ),
                SoftPreference(
                    constraint=IntentConstraint(
                        field_key="warranty_months",
                        operator="greater_than_or_equal",
                        expected=24,
                        unit="month",
                    ),
                    weight=20,
                ),
            ),
        ),
    )


def _validated_templates() -> tuple[BuyerIntentTemplate, ...]:
    taxonomy = load_bundled_taxonomy()
    if taxonomy.version != TEMPLATE_TAXONOMY_VERSION:
        raise BuyerIntentTemplateContractError(
            "buyer-intent templates require bundled taxonomy version "
            f"{TEMPLATE_TAXONOMY_VERSION}, found {taxonomy.version}"
        )

    known_categories = {
        category.key for category in taxonomy.categories if category.assignable_primary
    }
    known_fields = {field.key for field in taxonomy.fields}
    templates = tuple(sorted(_build_templates(), key=lambda item: item.key))
    keys = [item.key for item in templates]
    if len(keys) != len(set(keys)):
        raise BuyerIntentTemplateContractError("buyer-intent template keys must be unique")

    for template in templates:
        unknown_categories = set(template.structured_intent.category_keys) - known_categories
        if unknown_categories:
            unknown = ", ".join(sorted(unknown_categories))
            raise BuyerIntentTemplateContractError(
                f"template {template.key!r} references unknown categories: {unknown}"
            )
        constraints = template.structured_intent.hard_constraints + tuple(
            preference.constraint for preference in template.structured_intent.soft_preferences
        )
        unknown_fields = {item.field_key for item in constraints} - known_fields
        if unknown_fields:
            unknown = ", ".join(sorted(unknown_fields))
            raise BuyerIntentTemplateContractError(
                f"template {template.key!r} references unknown fields: {unknown}"
            )
    return templates


BUILTIN_BUYER_INTENT_TEMPLATES = _validated_templates()
_TEMPLATE_BY_KEY = {item.key: item for item in BUILTIN_BUYER_INTENT_TEMPLATES}


def list_buyer_intent_templates(
    *,
    category_key: str | None = None,
    use_case: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> BuyerIntentTemplatePage:
    normalized_category = category_key.strip().casefold() if category_key is not None else None
    normalized_use_case = use_case.strip().casefold() if use_case is not None else None
    items = tuple(
        item
        for item in BUILTIN_BUYER_INTENT_TEMPLATES
        if (
            normalized_category is None
            or normalized_category in item.structured_intent.category_keys
        )
        and (normalized_use_case is None or normalized_use_case in item.use_cases)
    )
    return BuyerIntentTemplatePage(items=items[offset : offset + limit], total=len(items))


def get_buyer_intent_template(template_key: str) -> BuyerIntentTemplate:
    normalized = template_key.strip().casefold()
    try:
        return _TEMPLATE_BY_KEY[normalized]
    except KeyError as exc:
        raise BuyerIntentTemplateNotFoundError("Buyer intent template not found") from exc
