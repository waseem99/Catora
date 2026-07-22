# HTTP JSON-schema enrichment provider

Catora's `http_json` adapter connects the provider-neutral gateway to a configured external
HTTPS endpoint without introducing a vendor SDK or provider-specific response format into
application code.

The adapter sends the existing versioned `ProviderRequest`: request identity, task type,
prompt version and fingerprint, system prompt, untrusted user payload, response JSON schema
and maximum output tokens. The API key is sent only as a bearer header and is never included
in the JSON payload or adapter representation.

The endpoint must return `output` plus `usage` containing non-negative input tokens, output
tokens and cost microunits. Catora assigns the configured provider/model identity, validates
the response contract, checks the reported cost against the reserved maximum, and then runs
the existing candidate, evidence, confidence and brand-control validation.

Production configuration requires an HTTPS endpoint, a non-placeholder API key, a model name
and an explicit maximum request cost. Transport, HTTP status, JSON and schema failures are
reported through sanitized provider-contract errors without response bodies or secrets.
