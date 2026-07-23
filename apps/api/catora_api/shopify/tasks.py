from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import cast

from celery import shared_task
from sqlalchemy import func, select, update

from catora_api.auditing.append_only_service import AppendOnlyAuditRunService
from catora_api.auditing.stateful_service import StatefulAuditRunService
from catora_api.database import SessionFactory
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    Category,
    IngestionJob,
    Product,
    ProductAttribute,
    ProductVariant,
    ReportJob,
)
from catora_api.ingestion.tasks import _run_ingestion_job
from catora_api.normalization.adapters import canonical_product_key
from catora_api.shopify.sync import queue_shopify_sync
from catora_api.shopify.webhooks import SHOPIFY_WEBHOOK_DELIVERY_TYPE
from catora_api.taxonomy.assignment import TaxonomyAssignmentService
from catora_api.taxonomy.resolution import classify_product

_PREVIEW_ATTRIBUTE_KEYS = ("description", "category", "product_type", "collections")


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_value(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return " ".join(parts) or None
    return None


def _string_list(snapshot: dict[str, object], key: str) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


async def _assign_taxonomy(workspace_id: uuid.UUID) -> tuple[str, int, int, int]:
    async with SessionFactory() as session:
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
        await session.commit()
        return taxonomy.package.version, assigned, ambiguous, unclassified


@shared_task(name="catora.shopify.sync", ignore_result=True)  # type: ignore[misc]
def run_shopify_sync(job_id: str, installation_id: str) -> None:
    asyncio.run(_run_shopify_sync(uuid.UUID(job_id), uuid.UUID(installation_id)))


async def _run_shopify_sync(job_id: uuid.UUID, installation_id: uuid.UUID) -> None:
    await _run_ingestion_job(job_id)
    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        job = await session.get(IngestionJob, job_id)
        if installation is None or job is None:
            return
        snapshot = dict(installation.input_snapshot)
        workspace_id = cast(uuid.UUID, installation.workspace_id)
        actor_user_id = _uuid_value(snapshot, "installed_by_user_id")
        source_id = _uuid_value(snapshot, "catalog_source_id")
        source = await session.get(CatalogSource, source_id) if source_id else None
        if job.status not in {"completed", "partially_completed"} or source is None:
            installation.input_snapshot = {
                **snapshot,
                "sync_status": "failed",
                "last_sync_failed_at": _now().isoformat(),
                "last_sync_error_type": str(job.checkpoint.get("error_type") or "SyncFailed"),
            }
            await session.commit()
            return
        if actor_user_id is None:
            installation.input_snapshot = {
                **snapshot,
                "sync_status": "failed",
                "last_sync_failed_at": _now().isoformat(),
                "last_sync_error_type": "MissingInstallationActor",
            }
            await session.commit()
            return

    try:
        taxonomy_version, assigned, ambiguous, unclassified = await _assign_taxonomy(
            workspace_id
        )
        async with SessionFactory() as session:
            audit_run = await StatefulAuditRunService().create_run(
                session,
                workspace_id=workspace_id,
                requested_by_user_id=actor_user_id,
                taxonomy_version=taxonomy_version,
                mode="full",
            )
            await session.commit()
            await AppendOnlyAuditRunService().execute_run(session, run_id=audit_run.id)

            installation = await session.get(ReportJob, installation_id)
            source = await session.get(CatalogSource, source_id) if source_id else None
            job = await session.get(IngestionJob, job_id)
            if installation is None or source is None or job is None:
                return
            product_count = await session.scalar(
                select(func.count(Product.id)).where(
                    Product.workspace_id == workspace_id,
                    Product.status == "active",
                    Product.deleted_at.is_(None),
                )
            )
            variant_count = await session.scalar(
                select(func.count(ProductVariant.id))
                .join(Product, Product.id == ProductVariant.product_id)
                .where(
                    ProductVariant.workspace_id == workspace_id,
                    ProductVariant.deleted_at.is_(None),
                    Product.status == "active",
                    Product.deleted_at.is_(None),
                )
            )
            completed_at = _now()
            current = dict(installation.input_snapshot)
            pending = _string_list(current, "pending_product_ids")
            installation.input_snapshot = {
                **current,
                "sync_status": "completed",
                "last_successful_sync_at": completed_at.isoformat(),
                "last_sync_job_id": str(job.id),
                "last_audit_run_id": str(audit_run.id),
                "product_count": int(product_count or 0),
                "variant_count": int(variant_count or 0),
                "warning_count": job.warning_count,
                "assigned_category_count": assigned,
                "ambiguous_category_count": ambiguous,
                "unclassified_category_count": unclassified,
                "pending_product_ids": [],
                "last_sync_error_type": None,
            }
            source.config = {
                **dict(source.config),
                "updated_after": completed_at.isoformat(),
            }
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    event_type="shopify.sync_completed",
                    entity_type="ingestion_job",
                    entity_id=job.id,
                    payload={
                        "catalog_source_id": str(source.id),
                        "product_count": int(product_count or 0),
                        "variant_count": int(variant_count or 0),
                        "warning_count": job.warning_count,
                        "audit_run_id": str(audit_run.id),
                    },
                )
            )
            await session.commit()
            if pending:
                await queue_shopify_sync(
                    session,
                    installation=installation,
                    reason="coalesced_webhook",
                    actor_user_id=actor_user_id,
                    product_ids=pending,
                )
    except Exception as exc:
        async with SessionFactory() as session:
            installation = await session.get(ReportJob, installation_id)
            if installation is None:
                return
            installation.input_snapshot = {
                **dict(installation.input_snapshot),
                "sync_status": "failed",
                "last_sync_failed_at": _now().isoformat(),
                "last_sync_error_type": type(exc).__name__,
            }
            await session.commit()
        raise


@shared_task(name="catora.shopify.webhook", ignore_result=True)  # type: ignore[misc]
def process_shopify_webhook(delivery_id: str) -> None:
    asyncio.run(_process_shopify_webhook(uuid.UUID(delivery_id)))


async def _process_shopify_webhook(delivery_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        delivery = await session.get(ReportJob, delivery_id)
        if (
            delivery is None
            or delivery.report_type != SHOPIFY_WEBHOOK_DELIVERY_TYPE
            or delivery.status == "completed"
        ):
            return
        snapshot = dict(delivery.input_snapshot)
        installation_id = _uuid_value(snapshot, "installation_id")
        installation = await session.get(ReportJob, installation_id) if installation_id else None
        if installation is None:
            delivery.status = "failed"
            await session.commit()
            return
        topic = snapshot.get("topic")
        product_id = snapshot.get("product_id")
        actor_user_id = _uuid_value(dict(installation.input_snapshot), "installed_by_user_id")
        workspace_id = cast(uuid.UUID, installation.workspace_id)
        source_id = _uuid_value(dict(installation.input_snapshot), "catalog_source_id")
        source = await session.get(CatalogSource, source_id) if source_id else None

        if topic == "app/uninstalled":
            current = dict(installation.input_snapshot)
            installation.status = "revoked"
            installation.input_snapshot = {
                **current,
                "encrypted_access_token": None,
                "encrypted_refresh_token": None,
                "sync_status": "revoked",
                "disconnected_at": _now().isoformat(),
            }
            if source is not None:
                source.status = "disconnected"
                source.credential_ref = None
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=None,
                    event_type="shopify.uninstalled",
                    entity_type="report_job",
                    entity_id=installation.id,
                    payload={"shop_domain": current.get("shop_domain")},
                )
            )
            delivery.status = "completed"
            await session.commit()
            return

        if installation.status != "active" or source is None:
            delivery.status = "ignored"
            await session.commit()
            return

        normalized_product_id: str | None = None
        if isinstance(product_id, str) and product_id:
            normalized_product_id = (
                product_id
                if product_id.startswith("gid://shopify/Product/")
                else f"gid://shopify/Product/{product_id}"
            )
        if topic == "products/delete" and normalized_product_id is not None:
            product = await session.scalar(
                select(Product).where(
                    Product.workspace_id == workspace_id,
                    Product.canonical_key
                    == canonical_product_key(source.id, normalized_product_id),
                )
            )
            if product is not None and product.deleted_at is None:
                deleted_at = _now()
                product.status = "deleted"
                product.deleted_at = deleted_at
                await session.execute(
                    update(ProductVariant)
                    .where(ProductVariant.product_id == product.id)
                    .values(deleted_at=deleted_at)
                )
                session.add(
                    AuditEvent(
                        workspace_id=workspace_id,
                        actor_user_id=None,
                        event_type="shopify.product_retired",
                        entity_type="product",
                        entity_id=product.id,
                        payload={"shopify_product_id": normalized_product_id},
                    )
                )
                await session.commit()

        job = await queue_shopify_sync(
            session,
            installation=installation,
            reason=str(topic or "shopify_webhook"),
            actor_user_id=actor_user_id,
            product_ids=[normalized_product_id] if normalized_product_id else [],
        )
        delivery.status = "completed"
        delivery.input_snapshot = {
            **snapshot,
            "processed_at": _now().isoformat(),
            "ingestion_job_id": str(job.id) if job is not None else None,
        }
        await session.commit()
