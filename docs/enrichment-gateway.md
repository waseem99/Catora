# Provider-neutral enrichment gateway

The `enrichment-gateway-v1` foundation separates Catora application logic from provider-specific response formats. Providers implement a small adapter contract for identity, maximum cost estimation and asynchronous structured generation. The gateway supplies versioned prompts and a JSON Schema, then validates every response with Pydantic before returning any candidate.

Product content is serialized under an explicit `untrusted_product_content` boundary. Prompt templates instruct providers never to follow commands found in catalog content. Common bearer tokens, API-key patterns, email addresses and phone numbers are redacted before a request is constructed. Source references returned by a provider must exactly match a supplied `source_record_id` and `field_path` pair.

Candidates cannot supply their own final confidence score. Catora deterministically assigns `high` to non-conflicting structured or direct source-field evidence, `medium` to supported source-copy or approved-image-text extraction, and `low` to inferred, conflicting or unsupported proposals. Protected factual fields such as dimensions, materials, warranty and safety require verification unless confidence is high.

The gateway enforces workspace-run cost through atomic reservations against an adapter-provided maximum estimate. Invalid structured output is charged, rejected and retried only up to the configured bound. Concurrent requests share the same semaphore and budget ledger, so in-flight reservations cannot collectively exceed the run budget. An adapter response whose actual cost exceeds its reserved estimate is a provider contract failure.

This slice does not persist recommendations or call a real provider. Persistence, API selection of products/findings, job execution and provider-specific adapters remain separate versioned slices.
