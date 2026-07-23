# Enterprise Northstar demo catalog

Issue #120 expands the prepared Northstar Living sales demonstration from a small fixture into a
deterministic enterprise-scale showcase.

## Scale

The enterprise seed creates:

- 1,000 products;
- 2,000 active variants/SKUs;
- 10 furniture and home categories;
- 5 canonical product attributes per product;
- 1 product image per product;
- deterministic audit findings for missing, conflicting and weak content;
- 5 prepared buyer-intent scenarios.

The original Cloudline Compact Three-Seat Sofa remains the primary guided-demo product. Its
missing width, source evidence, recommendation decisions and projected buyer-intent improvement
are preserved.

## Reset

For Docker Compose:

```bash
npm run demo:seed
```

The command runs `apps/api/scripts/seed_enterprise_demo.py`. It first recreates the validated base
workspace and then expands it to the enterprise target. Running it again deletes and recreates
only the dedicated `sales-demo` workspace.

New product, source, variant, attribute and image rows are flushed before dependent audit findings
are inserted, preserving the database foreign-key contract under PostgreSQL bulk execution.

The generated IDs remain stable because products, variants, intents and findings use deterministic
UUIDv5 identities. Timestamps and the presenter password may differ, but headline catalog,
finding and intent counts remain reproducible.

## Categories

- sofas;
- sectionals;
- chairs;
- recliners;
- dining tables;
- desks;
- storage;
- beds;
- outdoor seating;
- coffee tables.

## Seeded data quality distribution

The generator deliberately mixes:

- missing widths;
- conflicting widths and materials;
- missing care instructions;
- missing assembly requirements;
- missing materials;
- missing warranties;
- missing image alt text;
- weak descriptions.

The distribution is formula-driven rather than random. This keeps expected findings stable and
prevents demo resets from changing the story.

## Prepared buyer intents

1. Compact apartment sofa
2. Easy-care family dining
3. Apartment-friendly storage
4. Low-assembly home office
5. Weather-ready outdoor seating

The compact-apartment sofa remains the latest completed intent run so the existing five-step
guided route continues to open the correct scenario. The other four runs are persisted as older
prepared examples for future onboarding and demo navigation work.

## Shopify development-store export

Generate a Shopify-compatible product CSV after seeding:

```bash
npm run demo:export-shopify
```

The command writes:

```text
northstar-shopify-products.csv
```

The export contains one row per variant and standard Shopify product/variant columns. It also
contains product metafield columns for:

- `custom.width_mm`;
- `custom.material`;
- `custom.care_instructions`;
- `custom.assembly_required`;
- `custom.warranty_months`.

Create matching product metafield definitions in the Northstar Shopify development store before
importing the CSV. Missing and conflicting Catora attributes are exported as blank metafield
values so the Shopify-backed catalog preserves the intended diagnostic gaps.

The current image URLs use the reserved `example.test` host and are intentionally not expected to
load in Shopify. Issue #127 owns approved demo imagery and development-store automation.

## CI acceptance

The complete PostgreSQL migration job now:

1. upgrades to the latest migration;
2. runs the enterprise reset;
3. runs the enterprise reset a second time;
4. exports the Shopify CSV;
5. verifies exactly 1,000 titled product rows and 2,000 unique variant SKUs;
6. downgrades the migration chain by one revision.

This catches database constraints, cascade/reset problems, duplicate identities and broken export
semantics before the data reaches a live demo environment.
