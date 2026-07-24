from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings
from catora_api.db.models import AuditEvent, IngestionJob, ReportJob
from catora_api.shopify.installations import (
    SHOPIFY_INSTALLATION_TYPE,
    normalize_shop_domain,
)
from catora_api.worker import celery_app

SHOPIFY_WEBHOOK_DELIVERY_TYPE = "shopify_webhook_delivery"
SUPPORTED_TOPICS = {
    "app/scopes_update",
    "app/uninstalled",
    "bulk_operations/finish",
    "collections/create",
    "collections/update",
    "collections/delete",
    "products/create",
    "products/update",
    "products/delete",
}
_BULK_STATUSES = {"canceled", "canceling", "completed", "failed"}
_ACTIVE_JOB_STATUSES = ("queued", "validating", "running")
_REQUIRED_SCOPES = {"read_products"}
_MAX_SCOPE_COUNT = 50
ShopifyAppDistribution = Literal["custom", "public"]


class ShopifyWebhookError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyWebhookReceipt:
    delivery_id: uuid.UUID
    duplicate: bool
    distribution: ShopifyAppDistribution


def verify_shopify_webhook_hmac(
    body: bytes,
    supplied_signature: str,
    *,
    client_secret: str,
) -> bool:
    if not supplied_signature or not client_secret:
        return False
    digest = base64.b64encode(
        hmac.new(client_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(digest, supplied_signature)


def _delivery_id(webhook_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"catora:shopify:webhook:{webhook_id}")


def _payload_resource_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("id")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _bulk_metadata(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ShopifyWebhookError("Shopify bulk operation payload is invalid")
    operation_id = payload.get("admin_graphql_api_id")
    status_value = payload.get("status")
    operation_type = payload.get("type")
    if (
        not isinstance(operation_id, str)
        or not operation_id.startswith("gid://shopify/BulkOperation/")
        or not isinstance(status_value, str)
        or status_value.casefold() not in _BULK_STATUSES
        or operation_type != "query"
    ):
        raise ShopifyWebhookError("Shopify bulk operation payload is invalid")
    completed_at = payload.get("completed_at")
    error_code = payload.get("error_code")
    return {
        "bulk_operation_id": operation_id,
        "bulk_status": status_value.casefold(),
        "bulk_type": "query",
        "bulk_completed_at": completed_at if isinstance(completed_at, str) else None,
        "bulk_error_code": error_code if isinstance(error_code, str) else None,
    }


def _scope_list(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > _MAX_SCOPE_COUNT:
        raise ShopifyWebhookError("Shopify scope update payload is invalid")
    scopes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 100:
            raise ShopifyWebhookError("Shopify scope update payload is invalid")
        scopes.append(item.strip())
    return sorted(set(scopes))


def _scope_metadata(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ShopifyWebhookError("Shopify scope update payload is invalid")
    current = _scope_list(payload.get("current"))
    previous = _scope_list(payload.get("previous"))
    updated_at = payload.get("updated_at")
    shop_id = payload.get("shop_id")
    if updated_at is not None and not isinstance(updated_at, str):
        raise ShopifyWebhookError("Shopify scope update payload is invalid")
    if shop_id is not None and (
        not isinstance(shop_id, str) or not shop_id.startswith("gid://shopify/Shop/")
    ):
        raise ShopifyWebhookError("Shopify scope update payload is invalid")
    return {
        "current_scopes": current,
        "previous_scopes": previous,
        "scopes_updated_at": updated_at,
        "shop_gid": shop_id,
    }


def _installation_distribution(installation: ReportJob) -> ShopifyAppDistribution:
    value = installation.input_snapshot.get("distribution")
    return "public" if value == "public" else "custom"


def _verified_distribution(
    body: bytes,
    supplied_signature: str,
    *,
    settings: Settings,
) -> ShopifyAppDistribution:
    verified: list[ShopifyAppDistribution] = []
    if settings.shopify_enabled and verify_shopify_webhook_hmac(
        body,
        supplied_signature,
        client_secret=settings.shopify_client_secret,
    ):
        verified.append("custom")
    if settings.shopify_public_enabled and verify_shopify_webhook_hmac(
        body,
        supplied_signature,
        client_secret=settings.shopify_public_client_secret,
    ):
        verified.append("public")
    if not verified:
        raise ShopifyWebhookError("Shopify webhook signature is invalid")
    if len(verified) != 1:
        raise ShopifyWebhookError("Shopify webhook signature is ambiguous")
    return verified[0]


def _uuid_text(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _apply_scope_update(
    session: AsyncSession,
    *,
    installation: ReportJob,
    delivery: ReportJob,
) -> None:
    delivery_snapshot = dict(delivery.input_snapshot)
    current_scopes = set(
        item
        for item in delivery_snapshot.get("current_scopes", [])
        if isinstance(item, str)
    )
    compliant = current_scopes == _REQUIRED_SCOPES
    now = datetime.now(UTC)
    installation_snapshot = dict(installation.input_snapshot)
    prior_scope_block = installation_snapshot.get("scope_reauthorization_required") is True
    cancelled_jobs = 0

    if compliant:
        if installation.status == "refresh_required" and prior_scope_block:
            installation.status = "active"
        sync_status = installation_snapshot.get("sync_status")
        if sync_status == "reauthorization_required" and prior_scope_block:
            sync_status = "not_started"
        installation.input_snapshot = {
            **installation_snapshot,
            "granted_scopes": sorted(current_scopes),
            "previous_granted_scopes": delivery_snapshot.get("previous_scopes", []),
            "scope_reauthorization_required": False,
            "last_scope_update_at": delivery_snapshot.get("scopes_updated_at")
            or now.isoformat(),
            "last_scope_webhook_received_at": now.isoformat(),
            "sync_status": sync_status,
            "last_sync_error_type": (
                None
                if installation_snapshot.get("last_sync_error_type")
                == "ShopifyScopeMismatch"
                else installation_snapshot.get("last_sync_error_type")
            ),
        }
    else:
        installation.status = "refresh_required"
        source_id = _uuid_text(installation_snapshot.get("catalog_source_id"))
        if source_id is not None:
            result = await session.execute(
                update(IngestionJob)
                .where(
                    IngestionJob.catalog_source_id == source_id,
                    IngestionJob.status.in_(_ACTIVE_JOB_STATUSES),
                )
                .values(status="cancelled")
            )
            cancelled_jobs = int(getattr(result, "rowcount", 0) or 0)
        installation.input_snapshot = {
            **installation_snapshot,
            "granted_scopes": sorted(current_scopes),
            "previous_granted_scopes": delivery_snapshot.get("previous_scopes", []),
            "scope_reauthorization_required": True,
            "last_scope_update_at": delivery_snapshot.get("scopes_updated_at")
            or now.isoformat(),
            "last_scope_webhook_received_at": now.isoformat(),
            "sync_status": "reauthorization_required",
            "last_sync_error_type": "ShopifyScopeMismatch",
            "pending_product_ids": [],
            "pending_full_reconciliation": False,
        }

    session.add(
        AuditEvent(
            workspace_id=cast(uuid.UUID, installation.workspace_id),
            actor_user_id=None,
            event_type="shopify.scopes_updated",
            entity_type="report_job",
            entity_id=installation.id,
            payload={
                "distribution": _installation_distribution(installation),
                "current_scopes": sorted(current_scopes),
                "scope_compliant": compliant,
                "cancelled_job_count": cancelled_jobs,
            },
        )
    )
    delivery.status = "completed"
    delivery.input_snapshot = {
        **delivery_snapshot,
        "processed_at": now.isoformat(),
        "scope_compliant": compliant,
        "cancelled_job_count": cancelled_jobs,
    }


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
    if topic not in SUPPORTED_TOPICS:
        raise ShopifyWebhookError("Shopify webhook topic is not supported")
    shop = normalize_shop_domain(shop_domain)
    if not webhook_id:
        raise ShopifyWebhookError("Shopify webhook delivery ID is missing")
    distribution = _verified_distribution(
        body,
        supplied_signature,
        settings=settings,
    )

    delivery_id = _delivery_id(webhook_id)
    existing = await session.get(ReportJob, delivery_id)
    if existing is not None:
        existing_distribution = _installation_distribution(existing)
        snapshot_distribution = existing.input_snapshot.get("distribution")
        if snapshot_distribution in {"custom", "public"}:
            existing_distribution = cast(ShopifyAppDistribution, snapshot_distribution)
        if existing_distribution != distribution:
            raise ShopifyWebhookError(
                "Shopify webhook delivery identity does not match the original delivery"
            )
        return ShopifyWebhookReceipt(
            delivery_id=delivery_id,
            duplicate=True,
            distribution=distribution,
        )

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
    matches = [
        item
        for item in installations
        if item.input_snapshot.get("shop_domain") == shop
        and _installation_distribution(item) == distribution
    ]
    if not matches:
        raise ShopifyWebhookError("Shopify installation is not active")
    if len(matches) != 1:
        raise ShopifyWebhookError("Shopify installation identity is ambiguous")
    installation = matches[0]

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShopifyWebhookError("Shopify webhook payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ShopifyWebhookError("Shopify webhook payload is invalid")

    bounded_payload: dict[str, object]
    if topic == "app/scopes_update":
        bounded_payload = _scope_metadata(payload)
    elif topic == "bulk_operations/finish":
        bounded_payload = _bulk_metadata(payload)
    elif topic.startswith("products/"):
        bounded_payload = {"product_id": _payload_resource_id(payload)}
    elif topic.startswith("collections/"):
        bounded_payload = {"collection_id": _payload_resource_id(payload)}
    else:
        bounded_payload = {}
    delivery = ReportJob(
        id=delivery_id,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        report_type=SHOPIFY_WEBHOOK_DELIVERY_TYPE,
        status="queued",
        input_snapshot={
            "installation_id": str(installation.id),
            "shop_domain": shop,
            "distribution": distribution,
            "topic": topic,
            "webhook_id": webhook_id,
            "event_id": event_id,
            "triggered_at": triggered_at,
            "received_at": datetime.now(UTC).isoformat(),
            "payload_sha256": hashlib.sha256(body).hexdigest(),
            **bounded_payload,
        },
        template_version="shopify-webhook-v3",
    )
    session.add(delivery)
    if topic == "app/scopes_update":
        await _apply_scope_update(
            session,
            installation=installation,
            delivery=delivery,
        )
        await session.commit()
        return ShopifyWebhookReceipt(
            delivery_id=delivery.id,
            duplicate=False,
            distribution=distribution,
        )

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
    return ShopifyWebhookReceipt(
        delivery_id=delivery.id,
        duplicate=False,
        distribution=distribution,
    )
