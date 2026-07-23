from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import cast

from celery import shared_task
from sqlalchemy import select

from catora_api.auditing.append_only_service import AppendOnlyAuditRunService
from catora_api.auditing.stateful_service import StatefulAuditRunService
from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import (
    AuditEvent,
    BuyerIntent,
    CatalogSource,
    Category,
    IngestionJob,
    Product,
    ProductAttribute,
    ReportJob,
)
from catora_api.diagnostics.service import DiagnosticService
from catora_api.ingestion.factory import connector_for_source
from catora_api.ingestion.service import IngestionService
from catora_api.intents.execution import IntentRunService
from catora_api.intents.types import StructuredBuyerIntent
from catora_api.normalization.pipeline import CatalogNormalizationPipeline
from catora_api.storage import ObjectStorage
from catora_api.taxonomy.assignment import TaxonomyAssignmentService
from catora_api.taxonomy.resolution import classify_product

_PREVIEW_ATTRIBUTE_KEYS = ("description", "category", "product_type", "collections")


def _uuid_value(snapshot: dict[str, object], key: str) -> uuid.UUID:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Diagnostic snapshot is missing {key}")
    return uuid.UUID(value)


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return " ".join(parts) or None
    return None


def _prepared_intents(
    *,
    locale: str,
    market_id: uuid.UUID | None,
) -> tuple[tuple[str, StructuredBuyerIntent], ...]:
    definitions: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "Compact easy-care seating",
            {
                "query": "Which sofas fit a compact room and are easy to care for?",
                "category_keys": ["sofas_sectionals"],
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
            },
        ),
        (
            "Six-seat dining",
            {
                "query": "Which dining products support seating for six people?",
                "category_keys": ["dining_tables_chairs"],
                "hard_constraints": [
                    {
                        "field_key": "seating_capacity",
                        "operator": "greater_than_or_equal",
                        "expected": 6,
                        "unit": None,
                    }
                ],
                "soft_preferences": [],
            },
        ),
        (
            "Low-maintenance outdoor furniture",
            {
                "query": (
                    "Which outdoor furniture is clearly suitable for outdoor use "
                    "and easy care?"
                ),
                "category_keys": ["outdoor_furniture"],
                "hard_constraints": [
                    {
                        "field_key": "usage_environment",
                        "operator": "one_of",
                        "expected": ["outdoor", "indoor_outdoor"],
                        "unit": None,
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
                        "weight": 50,
                    }
                ],
            },
        ),
        (
            "Small-space storage",
            {
                "query": "Which storage products are narrow enough for a compact home?",
                "category_keys": ["storage_cabinets"],
                "hard_constraints": [
                    {
                        "field_key": "width_mm",
                        "operator": "less_than_or_equal",
                        "expected": 1200,
                        "unit": "mm",
                    }
                ],
                "soft_preferences": [],
            },
        ),
    )
    result: list[tuple[str, StructuredBuyerIntent]] = []
    for name, payload in definitions:
        result.append(
            (
                name,
                StructuredBuyerIntent.model_validate(
                    {**payload, "market_id": market_id, "locale": locale}
                ),
            )
        )
    return tuple(result)


@shared_task(name="catora.diagnostic.run", ignore_result=True)  # type: ignore[misc]
def run_diagnostic(assessment_id: str) -> None:
    asyncio.run(_run_diagnostic(uuid.UUID(assessment_id)))


async def _run_diagnostic(assessment_id: uuid.UUID) -> None:
    service = DiagnosticService()
    async with SessionFactory() as session:
        assessment = await session.get(ReportJob, assessment_id)
        if assessment is None or assessment.report_type != "prospect_diagnostic":
            return
        snapshot = dict(assessment.input_snapshot)
        actor_user_id = _uuid_value(snapshot, "operator_user_id")
        workspace_id = cast(uuid.UUID, assessment.workspace_id)
        source_id = _uuid_value(snapshot, "catalog_source_id")
        job_id = _uuid_value(snapshot, "ingestion_job_id")
        source = await session.get(CatalogSource, source_id)
        job = await session.get(IngestionJob, job_id)
        if source is None or job is None:
            await service.set_status(
                session,
                assessment,
                "failed",
                failure_code="MissingIngestionState",
                failure_detail="The uploaded source or ingestion job is unavailable.",
            )
            return

        try:
            await service.set_status(session, assessment, "ingesting")
            connector = await connector_for_source(source, ObjectStorage(get_settings()))
            ingestion = await IngestionService().run(
                session,
                source=source,
                job=job,
                connector=connector,
            )
            if ingestion.status not in {"completed", "partially_completed"}:
                raise RuntimeError("Catalog ingestion did not complete")

            await service.set_status(session, assessment, "normalizing")
            normalization = await CatalogNormalizationPipeline().normalize_job(
                session,
                source=source,
                job=job,
            )
            checkpoint = dict(job.checkpoint)
            checkpoint["normalization"] = normalization.as_dict()
            job.checkpoint = checkpoint
            await session.commit()

            await service.set_status(session, assessment, "categorizing")
            taxonomy = TaxonomyAssignmentService()
            await taxonomy.compile_workspace(session, workspace_id=workspace_id)
            products = list(
                (
                    await session.scalars(
                        select(Product)
                        .where(
                            Product.workspace_id == workspace_id,
                            Product.status == "active",
                            Product.deleted_at.is_(None),
                        )
                        .order_by(Product.id)
                    )
                ).all()
            )
            product_ids = [product.id for product in products]
            attributes_by_product: dict[uuid.UUID, dict[str, object]] = defaultdict(dict)
            if product_ids:
                rows = (
                    await session.execute(
                        select(
                            ProductAttribute.product_id,
                            ProductAttribute.key,
                            ProductAttribute.value,
                        ).where(
                            ProductAttribute.workspace_id == workspace_id,
                            ProductAttribute.product_id.in_(product_ids),
                            ProductAttribute.variant_id.is_(None),
                            ProductAttribute.key.in_(_PREVIEW_ATTRIBUTE_KEYS),
                            ProductAttribute.value_state == "present",
                        )
                    )
                ).all()
                for product_id, key, value in rows:
                    attributes_by_product[product_id][key] = value
            categories = list(
                (
                    await session.scalars(
                        select(Category).where(
                            Category.workspace_id == workspace_id,
                            Category.taxonomy_version == taxonomy.package.version,
                            Category.is_immutable.is_(True),
                        )
                    )
                ).all()
            )
            categories_by_key = {category.key: category for category in categories}
            assigned = 0
            ambiguous = 0
            unclassified = 0
            for product in products:
                values = attributes_by_product.get(product.id, {})
                category_text = " ".join(
                    text
                    for key in ("category", "product_type", "collections")
                    if (text := _text_value(values.get(key)))
                )
                result = classify_product(
                    taxonomy.package,
                    title=product.title,
                    category_text=category_text or None,
                    description=_text_value(values.get("description")),
                )
                if result.status == "assigned" and result.primary_category_key is not None:
                    category = categories_by_key.get(result.primary_category_key)
                    if category is not None:
                        product.primary_category_id = category.id
                        assigned += 1
                        continue
                if result.status == "ambiguous":
                    ambiguous += 1
                else:
                    unclassified += 1
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    event_type="diagnostic.taxonomy_assigned",
                    entity_type="report_job",
                    entity_id=assessment.id,
                    payload={
                        "taxonomy_version": taxonomy.package.version,
                        "assigned": assigned,
                        "ambiguous": ambiguous,
                        "unclassified": unclassified,
                    },
                )
            )
            await session.commit()
            await service.set_status(
                session,
                assessment,
                "auditing",
                assigned_category_count=assigned,
                ambiguous_category_count=ambiguous,
                unclassified_category_count=unclassified,
            )

            audit_run = await StatefulAuditRunService().create_run(
                session,
                workspace_id=workspace_id,
                requested_by_user_id=actor_user_id,
                taxonomy_version=taxonomy.package.version,
                mode="full",
            )
            await session.commit()
            await service.set_status(
                session,
                assessment,
                "auditing",
                audit_run_id=str(audit_run.id),
            )
            await AppendOnlyAuditRunService().execute_run(session, run_id=audit_run.id)

            await service.set_status(session, assessment, "matching")
            snapshot = dict(assessment.input_snapshot)
            market_value = snapshot.get("market_id")
            market_id = uuid.UUID(market_value) if isinstance(market_value, str) else None
            locale_value = snapshot.get("locale")
            locale = locale_value if isinstance(locale_value, str) else "en-US"
            intent_run_ids: list[str] = []
            intent_service = IntentRunService()
            for name, structured in _prepared_intents(locale=locale, market_id=market_id):
                intent = BuyerIntent(
                    workspace_id=workspace_id,
                    lineage_id=uuid.uuid4(),
                    name=name,
                    query=structured.query,
                    structured_intent=structured.model_dump(mode="json"),
                    source="template",
                    version=1,
                    approval_status="approved",
                )
                session.add(intent)
                await session.flush()
                intent_result = await intent_service.execute(
                    session,
                    workspace_id=workspace_id,
                    lineage_id=intent.lineage_id,
                    intent_version=1,
                )
                intent_run_ids.append(str(intent_result.run.id))
                session.add(
                    AuditEvent(
                        workspace_id=workspace_id,
                        actor_user_id=actor_user_id,
                        event_type="diagnostic.intent_completed",
                        entity_type="intent_run",
                        entity_id=intent_result.run.id,
                        payload={
                            "name": name,
                            "target_count": intent_result.summary.target_count,
                            "confident_match_count": intent_result.summary.confident_match_count,
                            "possible_match_missing_data_count": (
                                intent_result.summary.possible_match_missing_data_count
                            ),
                            "non_match_count": intent_result.summary.non_match_count,
                            "insufficient_category_data_count": (
                                intent_result.summary.insufficient_category_data_count
                            ),
                        },
                    )
                )
            await session.commit()

            await service.set_status(
                session,
                assessment,
                "preparing_reports",
                intent_run_ids=intent_run_ids,
            )
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    event_type="diagnostic.completed",
                    entity_type="report_job",
                    entity_id=assessment.id,
                    payload={
                        "catalog_source_id": str(source.id),
                        "ingestion_job_id": str(job.id),
                        "audit_run_id": str(audit_run.id),
                        "intent_run_ids": intent_run_ids,
                    },
                )
            )
            await session.commit()
            await service.set_status(session, assessment, "completed")
        except Exception as exc:
            await session.rollback()
            failed_assessment = await session.get(ReportJob, assessment_id)
            if failed_assessment is None:
                return
            stage = failed_assessment.status.replace("_", " ")
            await service.set_status(
                session,
                failed_assessment,
                "failed",
                failure_code=type(exc).__name__,
                failure_detail=f"The assessment stopped safely during {stage}.",
            )
            session.add(
                AuditEvent(
                    workspace_id=failed_assessment.workspace_id,
                    actor_user_id=actor_user_id,
                    event_type="diagnostic.failed",
                    entity_type="report_job",
                    entity_id=failed_assessment.id,
                    payload={"stage": stage, "error_type": type(exc).__name__},
                )
            )
            await session.commit()
