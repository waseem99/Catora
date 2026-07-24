from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings
from catora_api.db.models import (
    AuditEvent,
    ReportJob,
    ShopifyStoreInvitation,
    Workspace,
)
from catora_api.shopify.installations import normalize_shop_domain
from catora_api.shopify.webhooks import verify_shopify_webhook_hmac
from catora_api.worker import celery_app

SHOPIFY_COMPLIANCE_DELIVERY_TYPE = "shopify_compliance_delivery"
SHOPIFY_COMPLIANCE_TOPICS = {
    "customers/data_request",
    "customers/redact",
    "shop/redact",
}


class ShopifyComplianceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyComplianceReceipt:
    delivery_id: uuid.UUID
    duplicate: bool
    persisted: bool
    action: str


def _delivery_id(webhook_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"catora:shopify:compliance:{webhook_id}")


def _now() -> datetime:
    return datetime.now(UTC)


async def receive_shopify_compliance_webhook(
    session: AsyncSession,
    *,
    settings: Settings,
    body: bytes,
    topic: str,
    shop_domain: str,
    webhook_id: str,
    supplied_signature: str,
) -> ShopifyComplianceReceipt:
    if topic not in SHOPIFY_COMPLIANCE_TOPICS:
        raise ShopifyComplianceError("Shopify compliance topic is not supported")
    if not settings.shopify_public_enabled:
        raise ShopifyComplianceError("The Shopify public app is not configured")
    if not verify_shopify_webhook_hmac(
        body,
        supplied_signature,
        client_secret=settings.shopify_public_client_secret,
    ):
        raise ShopifyComplianceError("Shopify compliance signature is invalid")
    shop = normalize_shop_domain(shop_domain)
    if not webhook_id:
        raise ShopifyComplianceError("Shopify compliance delivery ID is missing")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShopifyComplianceError("Shopify compliance payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ShopifyComplianceError("Shopify compliance payload is invalid")

    delivery_id = _delivery_id(webhook_id)
    existing = await session.get(ReportJob, delivery_id)
    if existing is not None:
        if existing.report_type != SHOPIFY_COMPLIANCE_DELIVERY_TYPE:
            raise ShopifyComplianceError(
                "Shopify compliance delivery ID conflicts with another record"
            )
        action = existing.input_snapshot.get("action")
        return ShopifyComplianceReceipt(
            delivery_id=delivery_id,
            duplicate=True,
            persisted=True,
            action=action if isinstance(action, str) else "acknowledged",
        )

    invitation = await session.scalar(
        select(ShopifyStoreInvitation)
        .where(
            ShopifyStoreInvitation.shop_domain == shop,
            ShopifyStoreInvitation.activated_workspace_id.is_not(None),
        )
        .order_by(ShopifyStoreInvitation.created_at.desc())
        .limit(1)
    )
    if invitation is None or invitation.activated_workspace_id is None:
        action = (
            "unknown_shop_no_data"
            if topic == "shop/redact"
            else "no_customer_data_held"
        )
        return ShopifyComplianceReceipt(
            delivery_id=delivery_id,
            duplicate=False,
            persisted=False,
            action=action,
        )

    target_workspace = await session.get(
        Workspace,
        invitation.activated_workspace_id,
    )
    if target_workspace is None:
        action = "workspace_already_removed"
        return ShopifyComplianceReceipt(
            delivery_id=delivery_id,
            duplicate=False,
            persisted=False,
            action=action,
        )

    action = "delete_shop_workspace" if topic == "shop/redact" else "no_customer_data_held"
    status = "queued" if topic == "shop/redact" else "completed"
    received_at = _now()
    delivery = ReportJob(
        id=delivery_id,
        workspace_id=invitation.workspace_id,
        report_type=SHOPIFY_COMPLIANCE_DELIVERY_TYPE,
        status=status,
        input_snapshot={
            "topic": topic,
            "action": action,
            "distribution": "public",
            "webhook_id": webhook_id,
            "shop_domain_sha256": hashlib.sha256(shop.encode()).hexdigest(),
            "payload_sha256": hashlib.sha256(body).hexdigest(),
            "invitation_id": str(invitation.id),
            "target_workspace_id": str(target_workspace.id),
            "target_organization_id": str(target_workspace.organization_id),
            "received_at": received_at.isoformat(),
            "processed_at": received_at.isoformat() if status == "completed" else None,
        },
        template_version="shopify-compliance-v1",
    )
    session.add(delivery)
    session.add(
        AuditEvent(
            workspace_id=invitation.workspace_id,
            actor_user_id=None,
            event_type="shopify.compliance_received",
            entity_type="report_job",
            entity_id=delivery.id,
            payload={
                "topic": topic,
                "action": action,
                "shop_domain_sha256": delivery.input_snapshot["shop_domain_sha256"],
            },
        )
    )
    await session.commit()

    if topic == "shop/redact":
        try:
            celery_app.send_task(
                "catora.shopify.compliance",
                args=[str(delivery.id)],
            )
        except Exception as exc:
            delivery.status = "failed"
            delivery.input_snapshot = {
                **dict(delivery.input_snapshot),
                "failed_at": _now().isoformat(),
                "failure_type": type(exc).__name__,
            }
            await session.commit()
            raise ShopifyComplianceError(
                "Unable to enqueue Shopify shop deletion"
            ) from exc

    return ShopifyComplianceReceipt(
        delivery_id=delivery.id,
        duplicate=False,
        persisted=True,
        action=action,
    )
