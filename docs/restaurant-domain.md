# Restaurant and multi-location domain

The restaurant domain is an additive projection and evidence layer. It does not replace the
existing catalog, source, audit, recommendation, reporting, Shopify, Catalog Bridge, or Service
Visibility lifecycles.

## Ownership boundary

Restaurant commerce and approved public-profile systems remain authoritative for operational
facts. Catora stores immutable approved observations, deterministic normalized projections,
evidence states, recommendations, and human decisions.

Catora is not an ordering database and must not sit in the request path for carts, orders,
payments, refunds, loyalty, delivery, or live restaurant operations.

## Version and activation

The initial contract is `restaurant-domain/v1`. Runtime use is guarded by
`CATORA_RESTAURANT_DOMAIN_ENABLED`, which defaults to `false`. The migration is additive and does
not backfill existing catalog records automatically.

## Core entities

- restaurant brands and multi-location identities;
- aliases and deterministic canonical keys;
- locations, addresses, coordinates, hours, service modes, facilities, and cuisine types;
- service areas and ordering URLs;
- menus, sections, menu items, modifier groups, and modifier options;
- offers and promotions;
- immutable fact observations and versioned freshness policies.

Menu items may optionally link to an existing canonical `Product`. This link is additive and does
not change product ownership or introduce restaurant write-back.

## Fact states

Every volatile or review-sensitive fact can be represented as one of:

- `supported`;
- `partial`;
- `unsupported`;
- `stale`;
- `conflicting`;
- `inaccessible`.

Supported facts require a value. Invalidated or expired facts fail closed. A versioned freshness
policy can mark an otherwise supported observation stale after its maximum age.

Halal, allergen, dietary, price, promotion, hours, and availability facts must never be inferred
from missing evidence.

## Identity and determinism

Canonical keys are derived from Unicode-normalized, case-folded identity components and a SHA-256
suffix. Snapshot and projection hashes use canonical JSON ordering so logically identical input
produces the same hash independent of source list ordering.

Identity aliases remain reviewable. The model permits multiple records to share an alias so
ambiguous matches are represented rather than silently merged.

## Structured-data projections

The initial projection helpers can produce Organization, Restaurant, PostalAddress,
GeoCoordinates, Menu, MenuSection, MenuItem, and Offer JSON-LD from the current normalized
projection. Historical observations and unsupported facts are not serialized directly.

These helpers generate evidence-backed proposals. They do not publish to a website or profile.

## Restricted data

Restaurant adapters must reject customer, cart, order, payment, refund, loyalty, password, token,
session, delivery-person, and unrelated personal-address data before persistence. Secrets must not
enter payloads, logs, prompts, reports, issue bodies, or test artifacts.

## Migration and rollback

Revision `0020` creates only new tables and foreign keys. Existing catalog and connector data is
unchanged. Runtime rollback disables the feature flag while retaining immutable evidence.
Downgrading the schema is appropriate only before dependent production data exists or in a
controlled non-production environment.

## Next dependency slices

- #213 adds a restaurant profile to the existing Catalog Bridge.
- #214 composes restaurant rules through the existing deterministic audit engine.
- Ranchers activation remains gated by #222 and must not be hardcoded into these contracts.
