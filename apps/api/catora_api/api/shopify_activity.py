from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.db.models import ReportJob
from catora_api.schemas.shopify_installations import (
    ShopifyWebhookDeliveryView,
    ShopifyWebhookStatus,
    ShopifyWebhookTopic,
)
from catora_api.shopify.installations import ShopifyInstallationService
from catora_api.shopify.webhooks import SHOPIFY_WEBHOOK_DELIVERY_TYPE, SUPPORTED_TOPICS

router = APIRouter(tags=["shopify catalog ingestion"])
_DELIVERY_STATUSES = {"queued", "completed", "ignored", "failed"}


def _snapshot_text(snapshot: dict[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = _snapshot_text(snapshot, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _snapshot_datetime(snapshot: dict[str, object], key: str) -> datetime | None:
    value = _snapshot_text(snapshot, key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def delivery_view(delivery: ReportJob) -> ShopifyWebhookDeliveryView:
    snapshot = dict(delivery.input_snapshot)
    topic_value = _snapshot_text(snapshot, "topic")
    if topic_value not in SUPPORTED_TOPICS:
        raise ValueError("Stored Shopify webhook topic is invalid")
    status_value = delivery.status
    if status_value not in _DELIVERY_STATUSES:
        status_value = "failed"
    return ShopifyWebhookDeliveryView(
        id=delivery.id,
        topic=cast(ShopifyWebhookTopic, topic_value),
        status=cast(ShopifyWebhookStatus, status_value),
        signature_verified=True,
        received_at=_snapshot_datetime(snapshot, "received_at") or delivery.created_at,
        processed_at=_snapshot_datetime(snapshot, "processed_at"),
        product_id=_snapshot_text(snapshot, "product_id"),
        ingestion_job_id=_snapshot_uuid(snapshot, "ingestion_job_id"),
    )


@router.get(
    "/workspaces/{workspace_id}/shopify/webhooks/latest",
    response_model=ShopifyWebhookDeliveryView | None,
)
async def get_latest_shopify_webhook(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> ShopifyWebhookDeliveryView | None:
    await auth_service.membership(session, context.user.id, workspace_id)
    installation = await ShopifyInstallationService().find_installation(
        session,
        workspace_id=workspace_id,
    )
    if installation is None:
        return None

    deliveries = list(
        (
            await session.scalars(
                select(ReportJob)
                .where(
                    ReportJob.workspace_id == workspace_id,
                    ReportJob.report_type == SHOPIFY_WEBHOOK_DELIVERY_TYPE,
                )
                .order_by(ReportJob.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    installation_id = str(installation.id)
    for delivery in deliveries:
        if delivery.input_snapshot.get("installation_id") == installation_id:
            return delivery_view(delivery)
    return None
