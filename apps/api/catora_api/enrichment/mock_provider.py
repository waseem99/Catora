from __future__ import annotations

from collections.abc import Mapping

from catora_api.enrichment.types import (
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)


class DeterministicMockProvider:
    provider_name = "mock"
    model_name = "deterministic-catalog-v1"

    def estimate_cost_microunits(self, _request: ProviderRequest) -> int:
        return 100

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        payload = request.user_payload
        allowed_fields = _string_list(payload.get("allowed_fields"))
        original_values = _mapping(payload.get("original_values"))
        source = _first_source(payload.get("untrusted_product_content"))
        candidates = [
            _candidate(
                field_key=field_key,
                original_values=original_values,
                source=source,
                task_type=request.task_type,
            )
            for field_key in allowed_fields
        ]
        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            output={"candidates": candidates},
            usage=ProviderUsage(
                input_tokens=max(1, len(str(payload)) // 4),
                output_tokens=max(1, len(str(candidates)) // 4),
                cost_microunits=100,
            ),
        )


def _candidate(
    *,
    field_key: str,
    original_values: Mapping[str, object],
    source: Mapping[str, object],
    task_type: str,
) -> dict[str, object]:
    has_original = field_key in original_values
    proposed_value = (
        original_values[field_key]
        if has_original
        else f"Mock proposal for {field_key.replace('_', ' ')}"
    )
    claim_type = (
        "classification"
        if task_type == "classify_category"
        else "marketing_copy"
        if task_type
        in {
            "improve_title",
            "improve_description",
            "generate_faqs",
            "generate_alt_text",
        }
        else "fact"
    )
    evidence = []
    if source:
        evidence.append(
            {
                "source_record_id": source["source_record_id"],
                "field_path": source["field_path"],
                "excerpt": str(source.get("content", ""))[:2_000],
                "checksum": source.get("checksum"),
                "kind": source["kind"],
            }
        )
    return {
        "field_key": field_key,
        "proposed_value": proposed_value,
        "evidence": evidence,
        "inferred": not has_original,
        "evidence_conflict": False,
        "claim_type": claim_type,
        "explanation": "Deterministic development/test proposal.",
    }


def _first_source(value: object) -> Mapping[str, object]:
    if not isinstance(value, list) or not value:
        return {}
    source = value[0]
    return source if isinstance(source, Mapping) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
