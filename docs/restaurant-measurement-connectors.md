# Restaurant aggregate measurement connectors

Catora stores provider-neutral, aggregate observations for search, analytics, web-performance and external AI/search evidence. The module is disabled by default with `CATORA_MEASUREMENT_CONNECTORS_ENABLED=false`.

The repository runtime supports deterministic synthetic acceptance only. Google Search Console, GA4, PageSpeed Insights, CrUX, Bing Webmaster, IndexNow and external AI/search providers remain explicitly unavailable until each provider and account has passed scope, quota, terms, privacy, credential and acceptance review.

## Data boundary

Measurement observations may contain only approved aggregate dimensions:

- page or landing-page URL;
- query;
- country, locale or market;
- device;
- date;
- session source or medium;
- referrer host;
- metric scope;
- provider/model identifier for a dated external AI/search observation.

The contracts reject user, client, session, IP, email, phone, customer, order, transaction and address identifiers. Catora does not import raw event streams, customer journeys, orders, payments or revenue records through this module.

## Observations and definitions

Every observation records:

- provider and property identity;
- versioned metric key and source definition;
- integer microunits;
- allowlisted dimensions and deterministic dimension hash;
- explicit window start/end and timezone;
- complete, sampled, partial or unavailable state;
- current, stale, disconnected or unavailable freshness;
- observation time and deterministic observation hash.

Identical observations are idempotent. Provider properties and observations are tenant scoped and append-only. Disconnect revokes the managed credential reference, marks properties disconnected and changes current observations to disconnected without deleting evidence.

## Attribution and change annotations

An aggregate observation can be linked to a brand, location, menu, item or page only through an explicit exact, mapped, ambiguous or unmapped attribution record with method, confidence and evidence. Ambiguous attribution is not presented as fact.

Published changes, provider changes, campaigns, incidents and manual notes may be recorded as dated annotations. An annotation is context, not proof that a change caused a measurement movement.

## Comparisons and claims

Window comparisons require the same provider, property, metric version, dimensions and timezone. Deltas reconcile deterministically. Sampled or partial inputs cannot be presented as complete.

All comparisons are labelled observation-only or correlation-only. The contract prohibits causal claims. Catora does not guarantee citation, ranking, traffic, conversions, revenue or ROI.

## External AI/search observations

External AI/search samples remain separate from internal answer-readiness evaluation. They require an explicit provider/model, locale, market, exact metric definition and dated observation. A citation observation or referral aggregate does not prove provider influence or future visibility.

## Credentials and activation

Only managed credential references using `env:`, `vault:`, `secret:` or `synthetic:` are accepted by the service. Raw tokens are rejected. The public API exposes no live OAuth or provider-connect route in this release.

No Ranchers analytics, Search Console, business-profile, backlink, review or external AI/search account is connected by this repository implementation. Ranchers activation remains gated by issue #222 and explicit external acceptance.