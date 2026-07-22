# Buyer-intent parsing previews

Natural-language parsing produces an editable `StructuredBuyerIntent` preview. It does not create,
approve, execute or rank an intent.

- The query is normalized for display. Email, phone and secret patterns are redacted before the
  provider receives it.
- A versioned prompt and the full structured-intent JSON schema are sent through the configured
  provider-neutral adapter.
- Supplied category and field allowlists are enforced after provider output validation.
- The original normalized query and requested market/locale remain authoritative.
- Invalid output is retried only within the configured attempt and budget limits.
- The response includes provider/model identity, prompt fingerprint, attempts, token usage and cost.
- Saving the preview requires a separate explicit buyer-intent create or revise request.

The deterministic matcher remains the final eligibility engine. Model output never decides product
match status, coverage totals or rankings.
