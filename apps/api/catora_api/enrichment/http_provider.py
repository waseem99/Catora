from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from catora_api.enrichment.errors import ProviderContractError
from catora_api.enrichment.types import (
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)


class _HttpProviderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: dict[str, object]
    usage: ProviderUsage


class HttpJsonSchemaProvider:
    provider_name = "http_json"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_request_cost_microunits: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("HTTP enrichment provider endpoint must be an HTTP(S) URL")
        if not model_name.strip():
            raise ValueError("HTTP enrichment provider model name is required")
        if timeout_seconds <= 0:
            raise ValueError("HTTP enrichment provider timeout must be positive")
        if max_request_cost_microunits < 0:
            raise ValueError("HTTP enrichment provider maximum request cost cannot be negative")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._max_request_cost_microunits = max_request_cost_microunits
        self._client = client

    @property
    def model_name(self) -> str:
        return self._model_name

    def estimate_cost_microunits(self, _request: ProviderRequest) -> int:
        return self._max_request_cost_microunits

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if self._client is not None:
            return await self._generate(self._client, request)
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await self._generate(client, request)

    async def _generate(
        self,
        client: httpx.AsyncClient,
        request: ProviderRequest,
    ) -> ProviderResponse:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-catora-request-id": str(request.request_id),
            "x-catora-prompt-fingerprint": request.prompt_fingerprint,
        }
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        try:
            response = await client.post(
                self._endpoint,
                headers=headers,
                json=request.model_dump(mode="json"),
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise ProviderContractError("HTTP enrichment provider request timed out") from None
        except httpx.HTTPStatusError as exc:
            raise ProviderContractError(
                f"HTTP enrichment provider returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.RequestError:
            raise ProviderContractError("HTTP enrichment provider request failed") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderContractError(
                "HTTP enrichment provider response was not valid JSON"
            ) from None

        try:
            parsed = _HttpProviderPayload.model_validate(payload)
        except ValidationError:
            raise ProviderContractError(
                "HTTP enrichment provider response did not match the required contract"
            ) from None
        if parsed.usage.cost_microunits > self._max_request_cost_microunits:
            raise ProviderContractError(
                "HTTP enrichment provider reported cost above the configured maximum"
            )
        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            output=parsed.output,
            usage=parsed.usage,
        )

    def __repr__(self) -> str:
        return (
            "HttpJsonSchemaProvider("
            f"endpoint={self._endpoint!r}, model_name={self._model_name!r})"
        )
