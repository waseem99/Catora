from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from catora_api.auth.dependencies import SessionDependency, SettingsDependency
from catora_api.schemas.shopify_installations import ShopifyWebhookResponse
from catora_api.shopify.compliance import (
    ShopifyComplianceError,
    receive_shopify_compliance_webhook,
)

router = APIRouter(tags=["shopify compliance webhooks"])


@router.post(
    "/shopify/compliance",
    response_model=ShopifyWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def accept_shopify_compliance_webhook(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> ShopifyWebhookResponse:
    body = await request.body()
    try:
        receipt = await receive_shopify_compliance_webhook(
            session,
            settings=settings,
            body=body,
            topic=request.headers.get("x-shopify-topic", ""),
            shop_domain=request.headers.get("x-shopify-shop-domain", ""),
            webhook_id=request.headers.get("x-shopify-webhook-id", ""),
            supplied_signature=request.headers.get("x-shopify-hmac-sha256", ""),
        )
    except ShopifyComplianceError as exc:
        code = 401 if "signature" in str(exc).casefold() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return ShopifyWebhookResponse(
        duplicate=receipt.duplicate,
        delivery_id=receipt.delivery_id,
    )
