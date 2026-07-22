from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from catora_api.auth.dependencies import (
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.enrichment.errors import (
    BudgetExceededError,
    InvalidProviderOutputError,
    ProviderContractError,
)
from catora_api.enrichment.provider_factory import configured_provider
from catora_api.intents.parser import BuyerIntentParsingService
from catora_api.schemas.intents import BuyerIntentParsePreview, BuyerIntentParseRequest

router = APIRouter(prefix="/api/v1", tags=["buyer intents"])


@router.post(
    "/workspaces/{workspace_id}/buyer-intents/parse-preview",
    response_model=BuyerIntentParsePreview,
)
async def parse_buyer_intent_preview(
    workspace_id: uuid.UUID,
    payload: BuyerIntentParseRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    settings: SettingsDependency,
    context: CsrfContextDependency,
) -> BuyerIntentParsePreview:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "analysis.run"):
        raise AuthorizationError("Buyer intent authoring permission required")
    provider = configured_provider(
        provider_name=settings.enrichment_provider,
        environment=settings.environment,
        settings=settings,
    )
    if provider is None:
        raise HTTPException(status_code=503, detail="Enrichment provider is not configured")
    budget_microunits = (
        payload.budget_microunits or settings.enrichment_max_run_budget_microunits
    )
    if budget_microunits > settings.enrichment_max_run_budget_microunits:
        raise HTTPException(
            status_code=422,
            detail="Requested intent parsing budget exceeds the configured maximum",
        )
    parser = BuyerIntentParsingService(
        provider,
        budget_microunits=budget_microunits,
        concurrency_limit=settings.enrichment_concurrency_limit,
        max_attempts=settings.enrichment_max_attempts,
        max_output_tokens=settings.enrichment_max_output_tokens,
    )
    try:
        result = await parser.parse(
            payload.query,
            allowed_category_keys=payload.allowed_category_keys,
            allowed_field_keys=payload.allowed_field_keys,
            market_id=payload.market_id,
            locale=payload.locale,
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (InvalidProviderOutputError, ProviderContractError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Buyer-intent provider output was invalid",
        ) from exc
    return BuyerIntentParsePreview(
        structured_intent=result.structured_intent,
        provider_name=result.provider_name,
        model_name=result.model_name,
        prompt_version=result.prompt_version,
        prompt_fingerprint=result.prompt_fingerprint,
        attempt_count=result.attempt_count,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_microunits=result.cost_microunits,
    )
