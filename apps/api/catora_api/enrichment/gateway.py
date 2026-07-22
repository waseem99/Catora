from __future__ import annotations

import asyncio
import uuid

from pydantic import ValidationError

from catora_api.enrichment.budget import BudgetLedger
from catora_api.enrichment.errors import (
    BudgetExceededError,
    EnrichmentGatewayError,
    InvalidProviderOutputError,
    ProviderContractError,
)
from catora_api.enrichment.prompts import build_provider_request
from catora_api.enrichment.provider import ProviderAdapter
from catora_api.enrichment.types import (
    EnrichmentRequest,
    EnrichmentResult,
    ProviderEnvelope,
)
from catora_api.enrichment.validation import (
    validate_candidates,
    validate_provider_identity,
)

__all__ = [
    "BudgetExceededError",
    "BudgetLedger",
    "EnrichmentGateway",
    "EnrichmentGatewayError",
    "InvalidProviderOutputError",
    "ProviderContractError",
]


class EnrichmentGateway:
    def __init__(
        self,
        provider: ProviderAdapter,
        *,
        budget_microunits: int,
        concurrency_limit: int = 4,
        max_attempts: int = 2,
        max_output_tokens: int = 2_000,
    ) -> None:
        if concurrency_limit < 1:
            raise ValueError("concurrency_limit must be positive")
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if max_output_tokens < 1 or max_output_tokens > 32_000:
            raise ValueError("max_output_tokens must be between 1 and 32000")
        self._provider = provider
        self._ledger = BudgetLedger(budget_microunits)
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._max_attempts = max_attempts
        self._max_output_tokens = max_output_tokens

    @property
    def spent_microunits(self) -> int:
        return self._ledger.spent_microunits

    async def run(self, request: EnrichmentRequest) -> EnrichmentResult:
        request_id = uuid.uuid4()
        provider_request = build_provider_request(
            request,
            request_id=request_id,
            max_output_tokens=self._max_output_tokens,
        )
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            estimate = self._provider.estimate_cost_microunits(provider_request)
            reservation = await self._ledger.reserve(estimate)
            try:
                async with self._semaphore:
                    response = await self._provider.generate(provider_request)
            except Exception:
                await self._ledger.release(reservation)
                raise
            await self._ledger.settle(
                reservation,
                response.usage.cost_microunits,
            )
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            total_cost += response.usage.cost_microunits
            validate_provider_identity(
                self._provider,
                provider_name=response.provider_name,
                model_name=response.model_name,
            )
            try:
                envelope = ProviderEnvelope.model_validate(response.output)
                candidates = validate_candidates(request, envelope.candidates)
            except (ValidationError, InvalidProviderOutputError) as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    continue
                raise InvalidProviderOutputError(
                    "provider output remained invalid after "
                    f"{attempt} attempts: {exc}"
                ) from exc
            return EnrichmentResult(
                request_id=request_id,
                workspace_id=request.workspace_id,
                product_id=request.product_id,
                variant_id=request.variant_id,
                task_type=request.task_type,
                provider_name=self._provider.provider_name,
                model_name=self._provider.model_name,
                prompt_version=provider_request.prompt_version,
                prompt_fingerprint=provider_request.prompt_fingerprint,
                attempt_count=attempt,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_microunits=total_cost,
                candidates=candidates,
            )

        raise InvalidProviderOutputError(
            str(last_error or "provider output was invalid")
        )
