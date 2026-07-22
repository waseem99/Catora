from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from catora_api.auth.security import PasswordService
from catora_api.database import SessionFactory
from catora_api.db.models.audit import AuditFinding, AuditRun, RuleDefinition, RuleVersion
from catora_api.db.models.catalog import (
    CatalogSource,
    Category,
    EvidenceReference,
    IngestionJob,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    SourceRecord,
)
from catora_api.db.models.identity import Membership, Organization, User, Workspace
from catora_api.db.models.intents import BuyerIntent, IntentProductMatch, IntentRun
from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.demo.service import product_snapshot_hash

NAMESPACE = uuid.UUID("794b264a-675d-49d4-8154-dbc4c4298470")
WORKSPACE_SLUG = "sales-demo"
TAXONOMY_VERSION = "1.0.0"
CATEGORY_KEYS = ("sofas", "chairs", "dining_tables", "desks", "storage")
FIELD_LABELS = {
    "width_mm": "Product width",
    "care_instructions": "Care instructions",
    "assembly_required": "Assembly requirements",
    "material": "Material",
    "image_alt_text": "Image alt text",
    "description": "Product description",
    "warranty_months": "Warranty",
}


def uid(value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, value)


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def evidence_payload(
    *,
    source_record_id: uuid.UUID,
    field_path: str,
    excerpt: str,
) -> list[dict[str, object]]:
    return [
        {
            "source_record_id": str(source_record_id),
            "field_path": field_path,
            "excerpt": excerpt,
            "checksum": digest(excerpt),
        }
    ]


async def seed() -> None:
    supplied_password = os.getenv("CATORA_DEMO_PASSWORD")
    demo_password = supplied_password or secrets.token_urlsafe(14)
    password_service = PasswordService()
    now = datetime.now(UTC)

    async with SessionFactory() as session:
        organization = await session.scalar(
            select(Organization).where(Organization.slug == "catora-demo")
        )
        if organization is None:
            organization = Organization(
                id=uid("organization"),
                name="Catora Demo Retail Group",
                slug="catora-demo",
            )
            session.add(organization)
            await session.flush()

        existing_workspace = await session.scalar(
            select(Workspace).where(
                Workspace.organization_id == organization.id,
                Workspace.slug == WORKSPACE_SLUG,
            )
        )
        if existing_workspace is not None:
            await session.execute(delete(Workspace).where(Workspace.id == existing_workspace.id))
            await session.commit()

        user = await session.scalar(select(User).where(User.email == "demo@catora.local"))
        if user is None:
            user = User(
                id=uid("demo-user"),
                email="demo@catora.local",
                display_name="Catora Demo Presenter",
                password_hash=password_service.hash(demo_password),
                is_active=True,
            )
            session.add(user)
        else:
            user.display_name = "Catora Demo Presenter"
            user.password_hash = password_service.hash(demo_password)
            user.is_active = True
        await session.flush()

        workspace = Workspace(
            id=uid("workspace"),
            organization_id=organization.id,
            name="Northstar Living — Sales Demo",
            slug=WORKSPACE_SLUG,
        )
        session.add(workspace)
        await session.flush()
        session.add(
            Membership(
                id=uid("membership"),
                organization_id=organization.id,
                workspace_id=workspace.id,
                user_id=user.id,
                role="owner",
            )
        )

        source = CatalogSource(
            id=uid("catalog-source"),
            workspace_id=workspace.id,
            name="Northstar Living product export",
            source_type="csv",
            status="active",
            config={"mapping": "sales-demo-v1", "filename": "northstar-living.csv"},
        )
        job = IngestionJob(
            id=uid("ingestion-job"),
            workspace_id=workspace.id,
            catalog_source_id=source.id,
            status="completed",
            checkpoint={"row": 100},
            processed_count=100,
            success_count=100,
            rejection_count=0,
            warning_count=18,
            started_at=now,
            completed_at=now,
        )
        session.add_all([source, job])

        categories: dict[str, Category] = {}
        for key in CATEGORY_KEYS:
            category = Category(
                id=uid(f"category:{key}"),
                workspace_id=workspace.id,
                key=key,
                label=key.replace("_", " ").title(),
                taxonomy_version=TAXONOMY_VERSION,
                is_immutable=True,
            )
            categories[key] = category
            session.add(category)

        rule_versions: dict[str, RuleVersion] = {}
        for field_key, label in FIELD_LABELS.items():
            definition = RuleDefinition(
                id=uid(f"rule-definition:{field_key}"),
                workspace_id=workspace.id,
                key=f"builtin.demo.{field_key}",
                name=f"Demo {label}",
                rule_type="presence",
                description=f"Checks whether {label.lower()} is supported by source evidence.",
            )
            version = RuleVersion(
                id=uid(f"rule-version:{field_key}"),
                workspace_id=workspace.id,
                rule_definition_id=definition.id,
                version="1.0.0",
                specification={
                    "field_key": field_key,
                    "category_key": "sofas",
                    "severity": "high" if field_key == "width_mm" else "medium",
                },
                is_immutable=True,
            )
            rule_versions[field_key] = version
            session.add_all([definition, version])

        products: list[Product] = []
        source_records: dict[uuid.UUID, SourceRecord] = {}
        attributes_by_product: dict[uuid.UUID, dict[str, ProductAttribute]] = {}
        materials = ("Bouclé", "Performance velvet", "Oak", "Walnut", "Powder-coated steel")
        for index in range(100):
            category_key = CATEGORY_KEYS[index % len(CATEGORY_KEYS)]
            is_hero = index == 0
            title = (
                "Cloudline Compact Three-Seat Sofa"
                if is_hero
                else f"Northstar {category_key.replace('_', ' ').title()} {index:03d}"
            )
            product = Product(
                id=uid(f"product:{index}"),
                workspace_id=workspace.id,
                canonical_key=(
                    "demo:compact-cloud-sofa"
                    if is_hero
                    else f"demo:product:{index:03d}"
                ),
                title=title,
                primary_category_id=categories[category_key].id,
                status="active",
            )
            products.append(product)
            session.add(product)
            record_payload = {
                "id": f"northstar-{index:03d}",
                "title": title,
                "category": category_key,
                "description": (
                    "A compact apartment-friendly sofa in performance fabric. "
                    "Spot clean with a damp cloth and assemble the legs on delivery."
                    if is_hero
                    else f"A considered {category_key.replace('_', ' ')} for modern homes."
                ),
            }
            source_record = SourceRecord(
                id=uid(f"source-record:{index}"),
                workspace_id=workspace.id,
                catalog_source_id=source.id,
                ingestion_job_id=job.id,
                external_id=f"northstar-{index:03d}",
                record_type="product",
                payload=record_payload,
                content_hash=digest(record_payload),
                source_updated_at=now,
                snapshot_at=now,
            )
            source_records[product.id] = source_record
            session.add(source_record)

            width_missing = is_hero or index % 3 == 0
            care_missing = is_hero or index % 4 == 0
            assembly_missing = index % 5 == 0
            material_missing = index % 4 == 0
            warranty_missing = is_hero or index % 6 == 0
            attributes = {
                "width_mm": ProductAttribute(
                    id=uid(f"attribute:{index}:width_mm"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key="width_mm",
                    value=None if width_missing else 900 + (index % 12) * 100,
                    value_type="decimal",
                    unit="mm",
                    value_state="missing" if width_missing else "present",
                    transformer_version="sales-demo-v1",
                    confidence="high",
                ),
                "material": ProductAttribute(
                    id=uid(f"attribute:{index}:material"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key="material",
                    value=None if material_missing else materials[index % len(materials)],
                    value_type="string",
                    value_state="missing" if material_missing else "present",
                    transformer_version="sales-demo-v1",
                    confidence="high",
                ),
                "care_instructions": ProductAttribute(
                    id=uid(f"attribute:{index}:care"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key="care_instructions",
                    value=None if care_missing else "Spot clean with a damp cloth",
                    value_type="string",
                    value_state="missing" if care_missing else "present",
                    transformer_version="sales-demo-v1",
                    confidence="medium",
                ),
                "assembly_required": ProductAttribute(
                    id=uid(f"attribute:{index}:assembly"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key="assembly_required",
                    value=None if assembly_missing else index % 3 == 0,
                    value_type="boolean",
                    value_state="missing" if assembly_missing else "present",
                    transformer_version="sales-demo-v1",
                    confidence="high",
                ),
                "warranty_months": ProductAttribute(
                    id=uid(f"attribute:{index}:warranty"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    key="warranty_months",
                    value=None if warranty_missing else 12,
                    value_type="integer",
                    unit="months",
                    value_state="missing" if warranty_missing else "present",
                    transformer_version="sales-demo-v1",
                    confidence="high",
                ),
            }
            attributes_by_product[product.id] = attributes
            session.add_all(attributes.values())
            for variant_index in range(2):
                session.add(
                    ProductVariant(
                        id=uid(f"variant:{index}:{variant_index}"),
                        workspace_id=workspace.id,
                        product_id=product.id,
                        canonical_key=f"demo:product:{index:03d}:variant:{variant_index}",
                        sku=f"NST-{index:03d}-{variant_index + 1}",
                        title=f"{title} — {'Sand' if variant_index == 0 else 'Slate'}",
                        option_values={"colour": "Sand" if variant_index == 0 else "Slate"},
                    )
                )
            session.add(
                ProductImage(
                    id=uid(f"image:{index}"),
                    workspace_id=workspace.id,
                    product_id=product.id,
                    url=f"https://images.example.test/products/{index:03d}.jpg",
                    alt_text=None if index % 3 == 0 else f"{title} product view",
                    position=0,
                    checksum=digest(f"image-{index}"),
                )
            )
        await session.flush()

        hero = products[0]
        hero_record = source_records[hero.id]
        hero_excerpts = {
            "description": str(hero_record.payload["description"]),
            "care_instructions": "Spot clean with a damp cloth",
            "assembly_required": "Assemble the legs on delivery",
            "width_mm": "Width is not supplied in the source export",
            "warranty_months": "No warranty term is present in the source export",
        }
        for key, excerpt in hero_excerpts.items():
            attribute = attributes_by_product[hero.id].get(key)
            session.add(
                EvidenceReference(
                    id=uid(f"evidence:hero:{key}"),
                    workspace_id=workspace.id,
                    source_record_id=hero_record.id,
                    product_id=hero.id,
                    attribute_id=attribute.id if attribute is not None else None,
                    field_path=f"$.{key}",
                    excerpt=excerpt,
                    checksum=digest(excerpt),
                )
            )

        await session.flush()
        snapshot_hash = digest(
            {
                "workspace_id": str(workspace.id),
                "products": [str(product.id) for product in products],
                "version": "sales-demo-v1",
            }
        )
        audit_run = AuditRun(
            id=uid("audit-run"),
            workspace_id=workspace.id,
            requested_by_user_id=user.id,
            taxonomy_version=TAXONOMY_VERSION,
            mode="full",
            status="completed",
            source_snapshot_hash=snapshot_hash,
            product_snapshot_hashes={},
            rule_version_set=[str(version.id) for version in rule_versions.values()],
            progress_current=100,
            progress_total=100,
            score_summary={
                "overall_score_basis_points": 0,
                "confidence_basis_points": 10_000,
                "dimensions": {
                    "completeness": 6420,
                    "consistency": 7810,
                    "discoverability_readiness": 6280,
                },
            },
            finding_counts={},
            started_at=now,
            completed_at=now,
        )
        session.add(audit_run)
        await session.flush()

        finding_counter: Counter[str] = Counter()
        finding_index = 0
        for index, product in enumerate(products):
            record = source_records[product.id]
            attributes = attributes_by_product[product.id]
            conditions = [
                ("width_mm", attributes["width_mm"].value_state == "missing", "high"),
                (
                    "care_instructions",
                    attributes["care_instructions"].value_state == "missing",
                    "medium",
                ),
                (
                    "assembly_required",
                    attributes["assembly_required"].value_state == "missing",
                    "medium",
                ),
                ("material", attributes["material"].value_state == "missing", "high"),
                (
                    "warranty_months",
                    attributes["warranty_months"].value_state == "missing",
                    "medium",
                ),
                ("image_alt_text", index % 3 == 0, "medium"),
                ("description", index % 5 == 0, "low"),
            ]
            for field_key, should_create, severity in conditions:
                if not should_create:
                    continue
                finding_index += 1
                finding_counter[severity] += 1
                explanation = (
                    "The product width is absent, so Catora cannot prove that this "
                    "sofa fits a compact apartment."
                    if product.id == hero.id and field_key == "width_mm"
                    else f"{FIELD_LABELS[field_key]} is missing or unsupported by source evidence."
                )
                session.add(
                    AuditFinding(
                        id=uid(f"finding:{finding_index}"),
                        workspace_id=workspace.id,
                        audit_run_id=audit_run.id,
                        rule_version_id=rule_versions[field_key].id,
                        product_id=product.id,
                        severity=severity,
                        title=f"Missing {FIELD_LABELS[field_key].lower()}",
                        explanation=explanation,
                        fingerprint=digest(
                            {
                                "product_id": str(product.id),
                                "field_key": field_key,
                                "audit_run_id": str(audit_run.id),
                            }
                        ),
                        status="new",
                        category_key=CATEGORY_KEYS[index % len(CATEGORY_KEYS)],
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
                        failure_codes=[f"missing_{field_key}"],
                        evidence=evidence_payload(
                            source_record_id=record.id,
                            field_path=f"$.{field_key}",
                            excerpt=f"No supported {field_key} value in source record",
                        ),
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
        audit_run.finding_counts = {
            "critical": finding_counter["critical"],
            "high": finding_counter["high"],
            "medium": finding_counter["medium"],
            "low": finding_counter["low"],
            "informational": finding_counter["informational"],
        }
        total_checks = len(products) * 7
        passed_checks = total_checks - finding_index
        overall_score_basis_points = (passed_checks * 10_000) // total_checks
        audit_run.score_summary = {
            "overall_score_basis_points": overall_score_basis_points,
            "confidence_basis_points": 10_000,
            "evaluated_checks": total_checks,
            "failed_checks": finding_index,
            "formula": "passed_checks / evaluated_checks",
        }

        intent = BuyerIntent(
            id=uid("buyer-intent"),
            workspace_id=workspace.id,
            lineage_id=uid("buyer-intent-lineage"),
            name="Compact apartment sofa",
            query="Which three-seat sofas fit a compact apartment and are easy to care for?",
            structured_intent={
                "query": "Which three-seat sofas fit a compact apartment and are easy to care for?",
                "category_keys": ["sofas"],
                "hard_constraints": [
                    {
                        "field_key": "width_mm",
                        "operator": "less_than_or_equal",
                        "expected": 1900,
                        "unit": "mm",
                    }
                ],
                "soft_preferences": [
                    {
                        "constraint": {
                            "field_key": "care_instructions",
                            "operator": "contains",
                            "expected": "clean",
                            "unit": None,
                        },
                        "weight": 60,
                    }
                ],
                "market_id": None,
                "locale": "en-AE",
            },
            source="template",
            version=1,
            approval_status="approved",
        )
        intent_run = IntentRun(
            id=uid("intent-run"),
            workspace_id=workspace.id,
            buyer_intent_id=intent.id,
            status="completed",
            source_snapshot_hash=snapshot_hash,
            started_at=now,
            completed_at=now,
        )
        session.add_all([intent, intent_run])
        await session.flush()
        selected_products = products[:10]
        for index, product in enumerate(selected_products):
            if index == 0:
                status = "possible_match_missing_data"
                missing_fields = ["width_mm"]
                constraint_status = "missing"
                actual = None
            elif index in {1, 2, 3, 4}:
                status = "confident_match"
                missing_fields = []
                constraint_status = "supported"
                actual = attributes_by_product[product.id]["width_mm"].value
            else:
                status = "non_match"
                missing_fields = []
                constraint_status = "violated"
                actual = 2200 + index * 10
            session.add(
                IntentProductMatch(
                    id=uid(f"intent-match:{index}"),
                    workspace_id=workspace.id,
                    intent_run_id=intent_run.id,
                    product_id=product.id,
                    status=status,
                    score=Decimal("0.6000") if status != "non_match" else Decimal("0.0000"),
                    explanation={
                        "product_id": str(product.id),
                        "variant_id": None,
                        "category_key": "sofas",
                        "status": status,
                        "category_status": "supported",
                        "hard_constraints": [
                            {
                                "field_key": "width_mm",
                                "operator": "less_than_or_equal",
                                "status": constraint_status,
                                "expected": 1900,
                                "expected_unit": "mm",
                                "actual": actual,
                                "actual_unit": "mm" if actual is not None else None,
                                "evidence": [],
                            }
                        ],
                        "soft_preferences": [],
                        "soft_score_basis_points": 6000 if status != "non_match" else 0,
                        "missing_fields": missing_fields,
                        "violated_fields": ["width_mm"] if status == "non_match" else [],
                    },
                )
            )

        await session.flush()
        recommendation_hash = await product_snapshot_hash(
            session,
            workspace_id=workspace.id,
            product_id=hero.id,
        )
        recommendation = Recommendation(
            id=uid("recommendation"),
            workspace_id=workspace.id,
            product_id=hero.id,
            audit_finding_id=uid("finding:1"),
            status="ready_for_review",
            task_type="normalize_attributes",
            model_provider="catora-demo",
            model_name="deterministic-sales-demo",
            prompt_version="sales-demo-v1",
            cost_microunits=0,
            source_snapshot_hash=recommendation_hash,
            execution_metadata={
                "mode": "seeded-demo",
                "numbers_are_deterministic": True,
            },
        )
        session.add(recommendation)
        await session.flush()
        recommendation_fields = [
            RecommendationField(
                id=uid("recommendation-field:width_mm"),
                workspace_id=workspace.id,
                recommendation_id=recommendation.id,
                field_key="width_mm",
                original_value=None,
                proposed_value=1850,
                evidence=evidence_payload(
                    source_record_id=hero_record.id,
                    field_path="$.description",
                    excerpt="Compact apartment-friendly sofa; width requires supplier verification",
                ),
                confidence="medium",
                requires_verification=True,
                proposal_metadata={"claim_type": "factual", "inferred": True},
            ),
            RecommendationField(
                id=uid("recommendation-field:care_instructions"),
                workspace_id=workspace.id,
                recommendation_id=recommendation.id,
                field_key="care_instructions",
                original_value=None,
                proposed_value="Spot clean with a damp cloth",
                evidence=evidence_payload(
                    source_record_id=hero_record.id,
                    field_path="$.description",
                    excerpt="Spot clean with a damp cloth",
                ),
                confidence="high",
                requires_verification=False,
                proposal_metadata={"claim_type": "extracted_fact", "inferred": False},
            ),
            RecommendationField(
                id=uid("recommendation-field:warranty_months"),
                workspace_id=workspace.id,
                recommendation_id=recommendation.id,
                field_key="warranty_months",
                original_value=None,
                proposed_value=24,
                evidence=evidence_payload(
                    source_record_id=hero_record.id,
                    field_path="$.warranty",
                    excerpt="No warranty evidence is present",
                ),
                confidence="low",
                requires_verification=True,
                proposal_metadata={"claim_type": "factual", "inferred": True},
            ),
        ]
        session.add_all(recommendation_fields)
        await session.commit()

    print("Catora sales demo workspace reset successfully.")
    print(f"Workspace ID: {uid('workspace')}")
    print("Login: demo@catora.local")
    print(f"Password: {demo_password}")
    if supplied_password is None:
        print("The generated password is displayed once and is not stored in the repository.")


if __name__ == "__main__":
    asyncio.run(seed())
