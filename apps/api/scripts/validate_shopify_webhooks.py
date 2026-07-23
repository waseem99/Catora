from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from sqlalchemy import func, select

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import CatalogSource, IngestionJob, ReportJob, User, Workspace
from catora_api.shopify.installations import (
    SHOPIFY_INSTALLATION_TYPE,
    credential_reference,
)
from catora_api.shopify.sync import queue_shopify_sync
from catora_api.shopify.tasks import _process_shopify_webhook
from catora_api.shopify.webhooks import (
    SHOPIFY_WEBHOOK_DELIVERY_TYPE,
    receive_shopify_webhook,
)
from catora_api.worker import celery_app

SHOP = "northstar-living-demo.myshopify.com"


def signature(body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


async def validate() -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == "sales-demo")
        )
        user = await session.scalar(
            select(User).where(User.email == "demo@catora.local")
        )
        if workspace is None or user is None:
            raise RuntimeError("Run the enterprise demo seed first")

        installation = ReportJob(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            report_type=SHOPIFY_INSTALLATION_TYPE,
            status="active",
            input_snapshot={
                "shop_domain": SHOP,
                "workspace_id": str(workspace.id),
                "installed_by_user_id": str(user.id),
                "granted_scopes": ["read_products"],
                "token_mode": "expiring_offline",
                "sync_status": "not_started",
            },
            template_version="shopify-installation-v1",
        )
        session.add(installation)
        await session.flush()
        source = CatalogSource(
            workspace_id=workspace.id,
            name=f"{SHOP} Shopify catalog",
            source_type="shopify",
            status="ready",
            credential_ref=credential_reference(installation.id),
            config={
                "shop_domain": SHOP,
                "api_version": "2026-07",
                "updated_after": None,
                "normalization_aliases": {},
            },
        )
        session.add(source)
        await session.flush()
        installation.input_snapshot = {
            **dict(installation.input_snapshot),
            "catalog_source_id": str(source.id),
        }
        await session.commit()
        installation_id = installation.id
        source_id = source.id

        with patch.object(celery_app, "send_task") as send_task:
            first_job = await queue_shopify_sync(
                session,
                installation=installation,
                reason="initial_install",
                actor_user_id=user.id,
            )
            if first_job is None:
                raise RuntimeError("Initial Shopify sync was not queued")
            second_job = await queue_shopify_sync(
                session,
                installation=installation,
                reason="products/update",
                actor_user_id=user.id,
                product_ids=["gid://shopify/Product/123"],
            )
            if second_job is None or second_job.id != first_job.id:
                raise RuntimeError("Webhook burst did not coalesce behind the active job")
            if send_task.call_count != 1:
                raise RuntimeError("Coalesced Shopify sync enqueued duplicate tasks")

        body = json.dumps({"id": 123, "title": "Northstar Sofa"}).encode()
        with patch.object(celery_app, "send_task") as send_task:
            receipt = await receive_shopify_webhook(
                session,
                settings=settings,
                body=body,
                topic="products/update",
                shop_domain=SHOP,
                webhook_id="acceptance-product-update",
                event_id="acceptance-event",
                triggered_at="2026-07-23T10:00:00Z",
                supplied_signature=signature(body, settings.shopify_client_secret),
            )
            duplicate = await receive_shopify_webhook(
                session,
                settings=settings,
                body=body,
                topic="products/update",
                shop_domain=SHOP,
                webhook_id="acceptance-product-update",
                event_id="acceptance-event",
                triggered_at="2026-07-23T10:00:00Z",
                supplied_signature=signature(body, settings.shopify_client_secret),
            )
            if receipt.duplicate or not duplicate.duplicate:
                raise RuntimeError("Shopify webhook duplicate detection is incorrect")
            if send_task.call_count != 1:
                raise RuntimeError("Duplicate Shopify webhook enqueued duplicate work")

        delivery_count = await session.scalar(
            select(func.count(ReportJob.id)).where(
                ReportJob.report_type == SHOPIFY_WEBHOOK_DELIVERY_TYPE,
                ReportJob.id == receipt.delivery_id,
            )
        )
        if delivery_count != 1:
            raise RuntimeError("Shopify webhook delivery was not persisted idempotently")

        uninstall_body = b"{}"
        with patch.object(celery_app, "send_task"):
            uninstall = await receive_shopify_webhook(
                session,
                settings=settings,
                body=uninstall_body,
                topic="app/uninstalled",
                shop_domain=SHOP,
                webhook_id="acceptance-uninstall",
                event_id="acceptance-uninstall-event",
                triggered_at="2026-07-23T10:05:00Z",
                supplied_signature=signature(
                    uninstall_body,
                    settings.shopify_client_secret,
                ),
            )
        uninstall_delivery_id = uninstall.delivery_id

    await _process_shopify_webhook(uninstall_delivery_id)

    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        source = await session.get(CatalogSource, source_id)
        active_jobs = await session.scalar(
            select(func.count(IngestionJob.id)).where(
                IngestionJob.catalog_source_id == source_id,
                IngestionJob.status.in_(("queued", "validating", "running")),
            )
        )
        if installation is None or installation.status != "revoked":
            raise RuntimeError("Shopify uninstall did not revoke the installation")
        if (
            source is None
            or source.credential_ref is not None
            or source.status != "disconnected"
        ):
            raise RuntimeError("Shopify uninstall retained an active source credential")
        if active_jobs != 0:
            raise RuntimeError("Shopify uninstall retained active synchronization work")

    print("Shopify webhook and uninstall acceptance check passed.")


if __name__ == "__main__":
    asyncio.run(validate())
