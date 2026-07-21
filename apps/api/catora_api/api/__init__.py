from catora_api.api.auth import router as auth_router
from catora_api.api.ingestion import router as ingestion_router
from catora_api.api.public_catalog import router as public_catalog_router
from catora_api.api.shopify import router as shopify_router

__all__ = [
    "auth_router",
    "ingestion_router",
    "public_catalog_router",
    "shopify_router",
]
