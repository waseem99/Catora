from catora_api.api.audit_rules import router as audit_rules_router
from catora_api.api.audits import router as audits_router
from catora_api.api.auth import router as auth_router
from catora_api.api.catalog import router as catalog_router
from catora_api.api.catalog_identity import router as catalog_identity_router
from catora_api.api.enrichment_policy import router as enrichment_policy_router
from catora_api.api.ingestion import router as ingestion_router
from catora_api.api.public_catalog import router as public_catalog_router
from catora_api.api.recommendation_job_actions import (
    router as recommendation_job_actions_router,
)
from catora_api.api.recommendation_usage import router as recommendation_usage_router
from catora_api.api.recommendations import router as recommendations_router
from catora_api.api.shopify import router as shopify_router
from catora_api.api.taxonomy import router as taxonomy_router

__all__ = [
    "audit_rules_router",
    "audits_router",
    "auth_router",
    "catalog_identity_router",
    "catalog_router",
    "enrichment_policy_router",
    "ingestion_router",
    "public_catalog_router",
    "recommendation_job_actions_router",
    "recommendation_usage_router",
    "recommendations_router",
    "shopify_router",
    "taxonomy_router",
]
