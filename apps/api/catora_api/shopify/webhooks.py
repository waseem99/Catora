from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings
from catora_api.db.models import ReportJob
from catora_api.shopify.installations import (
    SHOPIFY_INSTALLATION_TYPE,
    normalize_shop_domain,
)
from catora_api.worker import celery_app

SHOPIFY_WEBHOOK_DELIVERY_TYPE = "shopify_webhook_delivery"
SUPPORTED_TOPICS = {
    "app/uninstalled",
    "products/create",
    "products/update",
    "products/delete",
}


class ShopifyWebhookError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyWebhookReceipt:
    delivery_id: uuid.UUID
    duplicate: bool


def verify_shopify_webhook_hmac(
    body: bytes,
    supplied_signature: str,
    *,
    client_secret: str,
) -> bool:
    if not supplied_signature:
        return False
    digest = base64.b64encode(
        hmac.new(client_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(digest, supplied_signature)


def _delivery_id(webhook_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"catora:shopify:webhook:{webhook_id}")


def _payload_product_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("id")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


async def receive_shopify_webhook(
    session: AsyncSession,
    *,
    settings: Settings,
    body: bytes,
    topic: str,
    shop_domain: str,
    webhook_id: str,
    event_id: str | None,
    triggered_at: str | None,
    supplied_signature: str,
) -> ShopifyWebhookReceipt:
    if not verify_shopify_webhook_hmac(
        body,
        supplied_signature,
        client_secret=settings.shopify_client_secret,
    ):
        raise ShopifyWebhookError("Shopify webhook signature is invalid")
    if topic not in SUPPORTED_TOPICS:
        raise ShopifyWebhookError("Shopify webhook topic is not supported")
    shop = normalize_shop_domain(shop_domain)
    if not webhook_id:
        raise ShopifyWebhookError("Shopify webhook delivery ID is missing")

    delivery_id = _delivery_id(webhook_id)
    existing = await session.get(ReportJob, delivery_id)
    if existing is not None:
        return ShopifyWebhookReceipt(delivery_id=delivery_id, duplicate=True)

    installations = list(
        (
            await session.scalars(
                select(ReportJob).where(
                    ReportJob.report_type == SHOPIFY_INSTALLATION_TYPE,
                    ReportJob.status.in_(("active", "refresh_required")),
                )
            )
        ).all()
    )
    installation = next(
        (
            item
            for item in installations
            if item.input_snapshot.get("shop_domain") == shop
        ),
        None,
    )
    if installation is None:
        raise ShopifyWebhookError("Shopify installation is not active")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShopifyWebhookError("Shopify webhook payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ShopifyWebhookError("Shopify webhook payload is invalid")

    product_id = _payload_product_id(payload)
    delivery = ReportJob(
        id=delivery_id,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        report_type=SHOPIFY_WEBHOOK_DELIVERY_TYPE,
        status="queued",
        input_snapshot={
            "installation_id": str(installation.id),
            "shop_domain": shop,
            "topic": topic,
            "webhook_id": webhook_id,
            "event_id": event_id,
            "triggered_at": triggered_at,
            "received_at": datetime.now(UTC).isoformat(),
            "payload_sha256": hashlib.sha256(body).hexdigest(),
            "product_id": product_id,
        },
        template_version="shopify-webhook-v1",
    )
    session.add(delivery)
    await session.commit()
    try:
        celery_app.send_task("catora.shopify.webhook", args=[str(delivery.id)])
    except Exception as exc:
        delivery.status = "failed"
        delivery.input_snapshot = {
            **dict(delivery.input_snapshot),
            "failure_type": type(exc).__name__,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        await session.commit()
        raise ShopifyWebhookError("Unable to enqueue Shopify webhook") from exc
    return ShopifyWebhookReceipt(delivery_id=delivery.id, duplicate=False)
