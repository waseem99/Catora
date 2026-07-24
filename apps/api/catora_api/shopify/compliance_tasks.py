from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from celery import shared_task

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import (
    AuditEvent,
    Organization,
    ReportJob,
    ShopifyStoreInvitation,
)
from catora_api.shopify.compliance import SHOPIFY_COMPLIANCE_DELIVERY_TYPE
from catora_api.storage import ObjectStorage


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@shared_task(name="catora.shopify.compliance", ignore_result=True)  # type: ignore[misc]
def process_shopify_compliance(delivery_id: str) -> None:
    asyncio.run(_process_shopify_compliance(uuid.UUID(delivery_id)))


async def _process_shopify_compliance(delivery_id: uuid.UUID) -> None:
    settings = get_settings()
    storage = ObjectStorage(settings)
    async with SessionFactory() as session:
        delivery = await session.get(ReportJob, delivery_id)
        if (
            delivery is None
            or delivery.report_type != SHOPIFY_COMPLIANCE_DELIVERY_TYPE
            or delivery.status == "completed"
        ):
            return
        snapshot = dict(delivery.input_snapshot)
        if snapshot.get("topic") != "shop/redact":
            delivery.status = "completed"
            delivery.input_snapshot = {
                **snapshot,
                "processed_at": _now().isoformat(),
            }
            await session.commit()
            return
        invitation_id = _snapshot_uuid(snapshot, "invitation_id")
        workspace_id = _snapshot_uuid(snapshot, "target_workspace_id")
        organization_id = _snapshot_uuid(snapshot, "target_organization_id")
        if workspace_id is None or organization_id is None:
            delivery.status = "failed"
            delivery.input_snapshot = {
                **snapshot,
                "failed_at": _now().isoformat(),
                "failure_type": "InvalidDeletionTarget",
            }
            await session.commit()
            return

    try:
        deleted_object_count = await storage.delete_prefix(f"workspaces/{workspace_id}")
    except Exception as exc:
        async with SessionFactory() as session:
            delivery = await session.get(ReportJob, delivery_id)
            if delivery is not None:
                delivery.status = "failed"
                delivery.input_snapshot = {
                    **dict(delivery.input_snapshot),
                    "failed_at": _now().isoformat(),
                    "failure_type": type(exc).__name__,
                }
                await session.commit()
        raise

    async with SessionFactory() as session:
        delivery = await session.get(ReportJob, delivery_id)
        if delivery is None or delivery.status == "completed":
            return
        snapshot = dict(delivery.input_snapshot)
        invitation = (
            await session.get(ShopifyStoreInvitation, invitation_id)
            if invitation_id is not None
            else None
        )
        organization = await session.get(Organization, organization_id)
        if invitation is not None:
            await session.delete(invitation)
        if organization is not None:
            await session.delete(organization)
        processed_at = _now()
        delivery.status = "completed"
        delivery.input_snapshot = {
            **snapshot,
            "invitation_id": None,
            "target_workspace_id": None,
            "target_organization_id": None,
            "deleted_object_count": deleted_object_count,
            "processed_at": processed_at.isoformat(),
            "failure_type": None,
        }
        session.add(
            AuditEvent(
                workspace_id=delivery.workspace_id,
                actor_user_id=None,
                event_type="shopify.shop_data_deleted",
                entity_type="report_job",
                entity_id=delivery.id,
                payload={
                    "topic": "shop/redact",
                    "shop_domain_sha256": snapshot.get("shop_domain_sha256"),
                    "deleted_object_count": deleted_object_count,
                },
            )
        )
        await session.commit()
