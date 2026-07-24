from catora_api.api.audit_rules import router as audit_rules_router
from catora_api.api.audits import router as audits_router
from catora_api.api.auth import router as auth_router
from catora_api.api.catalog import router as catalog_router
from catora_api.api.catalog_identity import router as catalog_identity_router
from catora_api.api.demo import router as demo_router
from catora_api.api.diagnostics import router as diagnostics_router
from catora_api.api.enrichment_policy import router as enrichment_policy_router
from catora_api.api.ingestion import router as ingestion_router
from catora_api.api.intent_breakdown import router as _intent_breakdown_router
from catora_api.api.intent_coverage import router as _intent_coverage_router
from catora_api.api.intent_parsing import router as intent_parsing_router
from catora_api.api.intent_runs import router as intent_runs_router
from catora_api.api.intent_suites import router as _intent_suites_router
from catora_api.api.intent_templates import router as intent_templates_router
from catora_api.api.intents import router as intents_router
from catora_api.api.public_catalog import router as public_catalog_router
from catora_api.api.recommendations import router as recommendations_router
from catora_api.api.shopify import router as shopify_router
from catora_api.api.shopify_activity import router as _shopify_activity_router
from catora_api.api.shopify_public import router as _shopify_public_router
from catora_api.api.taxonomy import router as taxonomy_router

_intent_coverage_router.include_router(_intent_breakdown_router)
_intent_suites_router.include_router(_intent_coverage_router)
intent_runs_router.include_router(_intent_suites_router)
shopify_router.include_router(_shopify_activity_router)
shopify_router.include_router(_shopify_public_router)

__all__ = [
    "audit_rules_router",
    "audits_router",
    "auth_router",
    "catalog_identity_router",
    "catalog_router",
    "demo_router",
    "diagnostics_router",
    "enrichment_policy_router",
    "ingestion_router",
    "intent_parsing_router",
    "intent_runs_router",
    "intent_templates_router",
    "intents_router",
    "public_catalog_router",
    "recommendations_router",
    "shopify_router",
    "taxonomy_router",
]
