from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import cast

from seed_sales_demo import (
    FIELD_LABELS,
    TAXONOMY_VERSION,
    WORKSPACE_SLUG,
    digest,
    evidence_payload,
    uid,
)
from seed_sales_demo import (
    seed as seed_base,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.database import SessionFactory
from catora_api.db.models.audit import AuditFinding, AuditRun, RuleVersion
from catora_api.db.models.catalog import (
    CatalogSource,
    Category,
    IngestionJob,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    SourceRecord,
)
from catora_api.db.models.identity import Workspace
from catora_api.db.models.intents import BuyerIntent, IntentProductMatch, IntentRun

PRODUCT_COUNT = 1_000
VARIANTS_PER_PRODUCT = 2
CATEGORY_KEYS = (
    "sofas",
    "sectionals",
    "chairs",
    "recliners",
    "dining_tables",
    "desks",
    "storage",
    "beds",
    "outdoor_seating",
    "coffee_tables",
)
MATERIALS = (
    "Bouclé",
    "Performance velvet",
    "Oak",
    "Walnut",
    "Powder-coated steel",
    "Rattan",
    "Linen blend",
    "Tempered glass",
)
COLLECTIONS = ("Aster", "Cloudline", "Harbour", "Mira", "Northstar", "Solace")
ADDITIONAL_INTENTS = (
    {
        "key": "easy-care-dining",
        "name": "Easy-care family dining",
        "query": "Which dining tables are easy to clean for a busy family?",
        "category_key": "dining_tables",
        "field_key": "care_instructions",
        "operator": "contains",
        "expected": "clean",
        "unit": None,
    },
    {
        "key": "apartment-storage",
        "name": "Apartment-friendly storage",
        "query": "Which storage pieces fit a compact apartment?",
        "category_key": "storage",
        "field_key": "width_mm",
        "operator": "less_than_or_equal",
        "expected": 1_200,
        "unit": "mm",
    },
    {
        "key": "low-assembly-desk",
        "name": "Low-assembly home office",
        "query": "Which desks need little or no assembly?",
        "category_key": "desks",
        "field_key": "assembly_required",
        "operator": "equals",
        "expected": False,
        "unit": None,
    },
    {
        "key": "weather-ready-seating",
        "name": "Weather-ready outdoor seating",
        "query": "Which outdoor seats use weather-ready materials?",
        "category_key": "outdoor_seating",
        "field_key": "material",
        "operator": "one_of",
        "expected": ["Rattan", "Powder-coated steel"],
        "unit": None,
    },
)


def _category_label(key: str) -> str:
    return key.replace("_", " ").title()


def _attribute_state(index: int, field_key: str) -> str:
    moduli = {
        "width_mm": 7,
        "care_instructions": 9,
        "assembly_required": 11,
        "material": 13,
        "warranty_months": 17,
    }
    modulus = moduli[field_key]
    if index % 97 == 0 and field_key in {"width_mm", "material"}:
        return "conflicting"
    return "missing" if index % modulus == 0 else "present"


def _attribute_value(index: int, field_key: str, state: str) -> object | None:
    if state != "present":
        return None
    if field_key == "width_mm":
        return 850 + (index % 16) * 90
    if field_key == "care_instructions":
        return "Wipe clean with a soft damp cloth"
    if field_key == "assembly_required":
        return index % 4 != 0
    if field_key == "material":
        return MATERIALS[index % len(MATERIALS)]
    if field_key == "warranty_months":
        return 12 + (index % 3) * 12
    raise ValueError(f"Unsupported demo field: {field_key}")


def _attribute_type(field_key: str) -> str:
    return {
        "width_mm": "decimal",
        "care_instructions": "string",
        "assembly_required": "boolean",
        "material": "string",
        "warranty_months": "integer",
    }[field_key]


def _attribute_unit(field_key: str) -> str | None:
    return {"width_mm": "mm", "warranty_months": "months"}.get(field_key)


async def _load_required(
    session: AsyncSession,
) -> tuple[
    Workspace,
    CatalogSource,
    IngestionJob,
    AuditRun,
    dict[str, Category],
    dict[str, RuleVersion],
]:
    workspace = await session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
    if workspace is None:
        raise RuntimeError("Base demo workspace was not created")
    source = await session.scalar(
        select(CatalogSource).where(
            CatalogSource.workspace_id == workspace.id,
            CatalogSource.name == "Northstar Living product export",
        )
    )
    job = await session.scalar(
        select(IngestionJob).where(IngestionJob.workspace_id == workspace.id)
    )
    audit_run = await session.scalar(
        select(AuditRun).where(
            AuditRun.workspace_id == workspace.id,
            AuditRun.status == "completed",
        )
    )
    if source is None or job is None or audit_run is None:
        raise RuntimeError("Base demo source, job or audit run is missing")

    categories = {
        category.key: category
        for category in (
            await session.scalars(
                select(Category).where(Category.workspace_id == workspace.id)
            )
        ).all()
    }
    versions = {}
    for version in (
        await session.scalars(
            select(RuleVersion).where(RuleVersion.workspace_id == workspace.id)
        )
    ).all():
        raw_key = version.specification.get("field_key")
        if isinstance(raw_key, str):
            versions[raw_key] = version
    return workspace, source, job, audit_run, categories, versions


async def _ensure_categories(
    session: AsyncSession,
    *,
    workspace: Workspace,
    categories: dict[str, Category],
) -> None:
    for key in CATEGORY_KEYS:
        if key in categories:
            continue
        category = Category(
            id=uid(f"category:{key}"),
            workspace_id=workspace.id,
            key=key,
            label=_category_label(key),
            taxonomy_version=TAXONOMY_VERSION,
            is_immutable=True,
        )
        categories[key] = category
        session.add(category)
    await session.flush()


async def _add_products(
    session: AsyncSession,
    *,
    workspace: Workspace,
    source: CatalogSource,
    job: IngestionJob,
    categories: dict[str, Category],
    audit_run: AuditRun,
    rule_versions: dict[str, RuleVersion],
) -> None:
    existing_products = cast(
        list[Product],
        (
            await session.scalars(
                select(Product)
                .where(Product.workspace_id == workspace.id)
                .order_by(Product.canonical_key)
            )
        ).all(),
    )
    start_index = len(existing_products)
    if start_index > PRODUCT_COUNT:
        raise RuntimeError("The base demo contains more products than the enterprise target")

    existing_findings = cast(
        list[AuditFinding],
        (
            await session.scalars(
                select(AuditFinding).where(AuditFinding.audit_run_id == audit_run.id)
            )
        ).all(),
    )
    finding_counter = Counter(finding.severity for finding in existing_findings)
    finding_index = len(existing_findings)

    now = audit_run.completed_at
    if now is None:
        raise RuntimeError("The base demo audit run is missing completed_at")

    for index in range(start_index, PRODUCT_COUNT):
        category_key = CATEGORY_KEYS[index % len(CATEGORY_KEYS)]
        collection = COLLECTIONS[index % len(COLLECTIONS)]
        category_label = _category_label(category_key)
        title = f"{collection} {category_label} {index:04d}"
        product = Product(
            id=uid(f"product:{index}"),
            workspace_id=workspace.id,
            canonical_key=f"demo:product:{index:04d}",
            title=title,
            primary_category_id=categories[category_key].id,
            status="active",
        )
        session.add(product)

        states = {
            field_key: _attribute_state(index, field_key)
            for field_key in (
                "width_mm",
                "material",
                "care_instructions",
                "assembly_required",
                "warranty_months",
            )
        }
        record_payload = {
            "id": f"northstar-{index:04d}",
            "handle": f"{category_key}-{index:04d}",
            "title": title,
            "category": category_key,
            "vendor": "Northstar Living",
            "description": (
                f"A considered {category_label.lower()} from the {collection} collection."
            ),
            "tags": [category_key, collection.casefold(), "sales-demo"],
        }
        source_record = SourceRecord(
            id=uid(f"source-record:{index}"),
            workspace_id=workspace.id,
            catalog_source_id=source.id,
            ingestion_job_id=job.id,
            external_id=f"northstar-{index:04d}",
            record_type="product",
            payload=record_payload,
            content_hash=digest(record_payload),
            source_updated_at=now,
            snapshot_at=now,
        )
        session.add(source_record)

        for field_key, state in states.items():
            session.add(
                ProductAttribute(
                    id=uid(f"attribute:{index}:{field_key}"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key=field_key,
                    value=_attribute_value(index, field_key, state),
                    value_type=_attribute_type(field_key),
                    unit=_attribute_unit(field_key),
                    value_state=state,
                    transformer_version="sales-demo-v2",
                    confidence="medium" if state == "conflicting" else "high",
                )
            )

        for variant_index in range(VARIANTS_PER_PRODUCT):
            colour = ("Sand", "Slate")[variant_index]
            session.add(
                ProductVariant(
                    id=uid(f"variant:{index}:{variant_index}"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    canonical_key=f"demo:product:{index:04d}:variant:{variant_index}",
                    sku=f"NST-{index:04d}-{variant_index + 1}",
                    title=f"{title} — {colour}",
                    option_values={"colour": colour},
                )
            )
        session.add(
            ProductImage(
                id=uid(f"image:{index}"),
                workspace_id=workspace.id,
                product_id=product.id,
                url=f"https://images.example.test/products/{index:04d}.jpg",
                alt_text=None if index % 8 == 0 else f"{title} product view",
                position=0,
                checksum=digest(f"image-{index}"),
            )
        )

        await session.flush()

        finding_conditions = [
            ("width_mm", states["width_mm"] != "present", "high"),
            ("care_instructions", states["care_instructions"] != "present", "medium"),
            ("assembly_required", states["assembly_required"] != "present", "medium"),
            ("material", states["material"] != "present", "high"),
            ("warranty_months", states["warranty_months"] != "present", "medium"),
            ("image_alt_text", index % 8 == 0, "medium"),
            ("description", index % 19 == 0, "low"),
        ]
        for field_key, should_create, severity in finding_conditions:
            if not should_create:
                continue
            finding_index += 1
            finding_counter[severity] += 1
            state = states.get(field_key, "missing")
            failure = "conflicting" if state == "conflicting" else "missing"
            session.add(
                AuditFinding(
                    id=uid(f"finding:{finding_index}"),
                    workspace_id=workspace.id,
                    audit_run_id=audit_run.id,
                    rule_version_id=rule_versions[field_key].id,
                    product_id=product.id,
                    severity=severity,
                    title=f"{failure.title()} {FIELD_LABELS[field_key].lower()}",
                    explanation=(
                        f"{FIELD_LABELS[field_key]} is {failure} or unsupported "
                        "by source evidence."
                    ),
                    fingerprint=digest(
                        {
                            "product_id": str(product.id),
                            "field_key": field_key,
                            "audit_run_id": str(audit_run.id),
                        }
                    ),
                    status="new",
                    category_key=category_key,
                    market_codes=["AE"],
                    field_key=field_key,
                    affected_value=None,
                    business_impact=(
                        "discoverability"
                        if field_key in {"width_mm", "image_alt_text", "description"}
                        else "data_quality"
                    ),
                    remediation_type=(
                        "add_structured_attribute"
                        if field_key not in {"image_alt_text", "description"}
                        else "improve_content"
                    ),
                    failure_codes=[f"{failure}_{field_key}"],
                    evidence=evidence_payload(
                        source_record_id=source_record.id,
                        field_path=f"$.{field_key}",
                        excerpt=f"No single supported {field_key} value in source record",
                    ),
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )

    await session.flush()
    products = cast(
        list[Product],
        (
            await session.scalars(
                select(Product)
                .where(Product.workspace_id == workspace.id)
                .order_by(Product.canonical_key)
            )
        ).all(),
    )
    snapshot_hash = digest(
        {
            "workspace_id": str(workspace.id),
            "products": [str(product.id) for product in products],
            "version": "sales-demo-v2",
        }
    )
    total_checks = len(products) * len(FIELD_LABELS)
    total_findings = sum(finding_counter.values())
    audit_run.source_snapshot_hash = snapshot_hash
    audit_run.progress_current = len(products)
    audit_run.progress_total = len(products)
    audit_run.finding_counts = {
        "critical": finding_counter["critical"],
        "high": finding_counter["high"],
        "medium": finding_counter["medium"],
        "low": finding_counter["low"],
        "informational": finding_counter["informational"],
    }
    audit_run.score_summary = {
        "overall_score_basis_points": ((total_checks - total_findings) * 10_000)
        // total_checks,
        "confidence_basis_points": 10_000,
        "evaluated_checks": total_checks,
        "failed_checks": total_findings,
        "formula": "passed_checks / evaluated_checks",
    }
    job.checkpoint = {"row": len(products)}
    job.processed_count = len(products)
    job.success_count = len(products)
    job.warning_count = total_findings
    job.rejection_count = 0


async def _replace_primary_intent_matches(
    session: AsyncSession,
    *,
    workspace: Workspace,
    audit_run: AuditRun,
    categories: dict[str, Category],
) -> None:
    intent = await session.get(BuyerIntent, uid("buyer-intent"))
    intent_run = await session.get(IntentRun, uid("intent-run"))
    if intent is None or intent_run is None:
        raise RuntimeError("The prepared primary buyer intent is missing")

    products = cast(
        list[Product],
        (
            await session.scalars(
                select(Product)
                .where(Product.workspace_id == workspace.id)
                .order_by(Product.canonical_key)
            )
        ).all(),
    )
    attributes = cast(
        list[ProductAttribute],
        (
            await session.scalars(
                select(ProductAttribute).where(
                    ProductAttribute.workspace_id == workspace.id,
                    ProductAttribute.variant_id.is_(None),
                )
            )
        ).all(),
    )
    attributes_by_product: dict[uuid.UUID, dict[str, ProductAttribute]] = {}
    for attribute in attributes:
        attributes_by_product.setdefault(attribute.product_id, {})[attribute.key] = attribute
    category_keys = {category.id: key for key, category in categories.items()}

    await session.execute(
        delete(IntentProductMatch).where(IntentProductMatch.intent_run_id == intent_run.id)
    )
    intent_run.source_snapshot_hash = audit_run.source_snapshot_hash

    for product in products:
        category_key = category_keys.get(product.primary_category_id)
        width = attributes_by_product.get(product.id, {}).get("width_mm")
        width_state = width.value_state if width is not None else "missing"
        width_value = width.value if width is not None and width_state == "present" else None

        if category_key != "sofas":
            status = "non_match"
            category_status = "violated"
            constraint_status = "missing"
            missing_fields: list[str] = []
            violated_fields = ["category"]
            score = 0
        elif width_state in {"missing", "unknown"}:
            status = "possible_match_missing_data"
            category_status = "supported"
            constraint_status = "missing"
            missing_fields = ["width_mm"]
            violated_fields = []
            score = 6_000
        elif width_state == "conflicting":
            status = "possible_match_missing_data"
            category_status = "supported"
            constraint_status = "conflicting"
            missing_fields = ["width_mm"]
            violated_fields = []
            score = 4_000
        elif isinstance(width_value, int | float) and width_value <= 1_900:
            status = "confident_match"
            category_status = "supported"
            constraint_status = "supported"
            missing_fields = []
            violated_fields = []
            score = 8_000
        else:
            status = "non_match"
            category_status = "supported"
            constraint_status = "violated"
            missing_fields = []
            violated_fields = ["width_mm"]
            score = 0

        hard_constraints = (
            []
            if category_key != "sofas"
            else [
                {
                    "field_key": "width_mm",
                    "operator": "less_than_or_equal",
                    "status": constraint_status,
                    "expected": 1_900,
                    "expected_unit": "mm",
                    "actual": width_value,
                    "actual_unit": "mm" if width_value is not None else None,
                    "evidence": [],
                }
            ]
        )
        session.add(
            IntentProductMatch(
                id=uid(f"intent-match:enterprise:{product.id}"),
                workspace_id=workspace.id,
                intent_run_id=intent_run.id,
                product_id=product.id,
                status=status,
                score=Decimal(score) / Decimal(10_000),
                explanation={
                    "product_id": str(product.id),
                    "variant_id": None,
                    "category_key": category_key,
                    "status": status,
                    "category_status": category_status,
                    "hard_constraints": hard_constraints,
                    "soft_preferences": [],
                    "soft_score_basis_points": score,
                    "missing_fields": missing_fields,
                    "violated_fields": violated_fields,
                },
            )
        )


async def _add_intent_scenarios(
    session: AsyncSession,
    *,
    workspace: Workspace,
    audit_run: AuditRun,
) -> None:
    completed_at = audit_run.completed_at
    if completed_at is None:
        raise RuntimeError("The demo audit run is missing completed_at")
    older_time = completed_at - timedelta(minutes=1)

    products = cast(
        list[Product],
        (
            await session.scalars(
                select(Product)
                .where(Product.workspace_id == workspace.id)
                .order_by(Product.canonical_key)
                .limit(40)
            )
        ).all(),
    )
    for scenario_index, scenario in enumerate(ADDITIONAL_INTENTS):
        key = str(scenario["key"])
        intent = BuyerIntent(
            id=uid(f"buyer-intent:{key}"),
            workspace_id=workspace.id,
            lineage_id=uid(f"buyer-intent-lineage:{key}"),
            name=str(scenario["name"]),
            query=str(scenario["query"]),
            structured_intent={
                "query": scenario["query"],
                "category_keys": [scenario["category_key"]],
                "hard_constraints": [
                    {
                        "field_key": scenario["field_key"],
                        "operator": scenario["operator"],
                        "expected": scenario["expected"],
                        "unit": scenario["unit"],
                    }
                ],
                "soft_preferences": [],
                "market_id": None,
                "locale": "en-AE",
            },
            source="template",
            version=1,
            approval_status="approved",
        )
        run = IntentRun(
            id=uid(f"intent-run:{key}"),
            workspace_id=workspace.id,
            buyer_intent_id=intent.id,
            status="completed",
            source_snapshot_hash=audit_run.source_snapshot_hash,
            started_at=older_time,
            completed_at=older_time,
        )
        session.add_all([intent, run])
        await session.flush()

        scenario_products = products[scenario_index * 10 : scenario_index * 10 + 10]
        for product_index, product in enumerate(scenario_products):
            status = (
                "confident_match"
                if product_index < 4
                else "possible_match_missing_data"
                if product_index < 7
                else "non_match"
            )
            missing_fields = (
                [str(scenario["field_key"])]
                if status == "possible_match_missing_data"
                else []
            )
            violated_fields = (
                [str(scenario["field_key"])] if status == "non_match" else []
            )
            score = 8_000 if status == "confident_match" else 5_000 if missing_fields else 0
            session.add(
                IntentProductMatch(
                    id=uid(f"intent-match:{key}:{product.id}"),
                    workspace_id=workspace.id,
                    intent_run_id=run.id,
                    product_id=product.id,
                    status=status,
                    score=Decimal(score) / Decimal(10_000),
                    explanation={
                        "product_id": str(product.id),
                        "variant_id": None,
                        "category_key": scenario["category_key"],
                        "status": status,
                        "category_status": "supported",
                        "hard_constraints": [],
                        "soft_preferences": [],
                        "soft_score_basis_points": score,
                        "missing_fields": missing_fields,
                        "violated_fields": violated_fields,
                    },
                )
            )


async def seed_enterprise() -> None:
    await seed_base()
    async with SessionFactory() as session:
        workspace, source, job, audit_run, categories, rule_versions = (
            await _load_required(session)
        )
        await _ensure_categories(session, workspace=workspace, categories=categories)
        await _add_products(
            session,
            workspace=workspace,
            source=source,
            job=job,
            categories=categories,
            audit_run=audit_run,
            rule_versions=rule_versions,
        )
        await _replace_primary_intent_matches(
            session,
            workspace=workspace,
            audit_run=audit_run,
            categories=categories,
        )
        await _add_intent_scenarios(
            session,
            workspace=workspace,
            audit_run=audit_run,
        )
        await session.commit()

    print(
        "Enterprise showcase ready: "
        f"{PRODUCT_COUNT} products, {PRODUCT_COUNT * VARIANTS_PER_PRODUCT} variants, "
        f"{1 + len(ADDITIONAL_INTENTS)} buyer-intent scenarios."
    )


if __name__ == "__main__":
    asyncio.run(seed_enterprise())
