# Restaurant answer evaluation

Catora evaluates whether approved restaurant evidence can answer practical brand, branch,
menu, price, hours, delivery, facility, dietary, halal, allergen and offer questions.

## Internal evaluation

`restaurant-answer-evaluation/v1` is deterministic. Each run records:

- the immutable suite version and checksum;
- the restaurant entity and exact approved evidence snapshot;
- observed, effective and expiry timestamps;
- supported, partial, unsupported, stale, conflicting or inaccessible state;
- exact fact keys and evidence identifiers used for each result;
- a deterministic input checksum for idempotency and before/after comparison.

Missing, expired, invalidated, inaccessible or conflicting evidence never becomes a confident
answer. Internal readiness does not imply that a search engine or AI provider cites the brand.

## External observations

External citation samples have a separate append-only persistence contract containing provider,
model or surface, locale, exact query, observation time, response digest, cited URLs and factual
accuracy. Catora stores no raw provider response in this contract.

No provider is enabled by this module. Live sampling requires separate provider discovery,
account-level acceptance, legal and cost approval, rate limits and a provider-specific feature
gate.

## Runtime gate

New evaluations require both:

```text
CATORA_RESTAURANT_DOMAIN_ENABLED=true
CATORA_RESTAURANT_ANSWER_EVALUATION_ENABLED=true
```

The answer-evaluation gate defaults off. Historical results remain readable when new evaluation
is disabled.

## Safety boundary

The module does not publish content, alter restaurant facts, query private pages, access customer
or order data, train external models, manipulate prompts, or guarantee rankings, citations,
traffic, revenue or ROI.
