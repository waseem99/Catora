# Restaurant Catalog Bridge profile

The `restaurant/v1` profile extends the existing signed and resumable Catalog Bridge. It does not
create a second transport, source lifecycle, credential store, object-storage layout, checkpoint
mechanism, or ingestion worker.

## Runtime boundary

The bridge runs inside the approved restaurant backend and reads only explicitly mapped business
facts. Catora never receives a MongoDB URI and is never placed in the cart, order, payment, menu
availability, or delivery request path.

The restaurant profile requires both existing global safety gates:

- `CATORA_CATALOG_BRIDGE_ENABLED=true`;
- `CATORA_RESTAURANT_DOMAIN_ENABLED=true`.

Each source must also be provisioned explicitly with profile `restaurant/v1`. Existing catalog
bridge sources remain profile `catalog/v1` and are unaffected.

## Allowed records

One batch record represents a restaurant brand and may include:

- public brand identity and aliases;
- public branch identity, address, coordinates, phone, URLs, hours, service modes, facilities,
  cuisine types, and service areas;
- menus, sections, items, media, prices, availability states, dietary/allergen facts, and explicit
  modifier groups/options;
- offers or promotions linked to branch or menu-item identities;
- source update timestamps and deterministic external IDs.

The profile is strict and versioned. Unknown top-level fields fail validation.

## Prohibited records

Recursive validation rejects cart, customer, order, payment, refund, loyalty, password, token,
session, rider, driver, and related transactional fields before a batch is accepted. Raw secrets
must not be placed in payloads, logs, prompts, GitHub issues, reports, or CI artifacts.

Public restaurant addresses are allowed. Customer or delivery-person addresses are prohibited by
the absence of any customer/order/delivery-person record contract.

## Snapshot lifecycle

1. An owner or admin provisions a restaurant bridge source and receives one revocable credential.
2. The backend starts a snapshot with declared brand, location, and menu-item totals.
3. Signed ordered batches are uploaded and stored in the existing workspace/source prefix.
4. Retries reuse the same sequence and checksum; changed or out-of-order replays fail closed.
5. Completion requires batch and nested entity counts to reconcile exactly.
6. The existing ingestion worker stores immutable `restaurant_brand` source records.
7. The restaurant normalizer projects approved facts into revision `0020` tables and records
   immutable fact observations.
8. Repeating an identical complete snapshot updates no logical identity and creates no duplicate
   source record or fact observation.

## Node and Mongo integration

`RestaurantCatalogBridgeClient` provides signed, resumable uploads. `mongoRestaurantBrands` and
`runMongoRestaurantBridge` require an explicit `mapBrand` callback; there is deliberately no broad
restaurant schema discovery because the backend owner must choose the approved allowlist.

A dry run validates the complete mapped stream and reconciles brand, location, and menu-item totals
before network delivery.

## Failure isolation

If Catora is unavailable, the bridge command fails or retries independently. Restaurant ordering,
pricing, availability, and deployment continue unchanged. Credentials can be rotated or revoked
through the existing Catalog Bridge source lifecycle.

## Ranchers gate

This reusable profile contains no Ranchers-specific schema or configuration. Ranchers activation
remains blocked by issue #222 until production readiness, approved fields, owners, safe access, and
operator acceptance are recorded.
