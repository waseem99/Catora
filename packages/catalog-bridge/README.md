# Catora Catalog Bridge

Connect an existing server-side Node.js/MongoDB commerce project to Catora without giving Catora database access.

The bridge reads products through the project's existing Mongoose model, maps only allowlisted catalog fields, validates them locally, and sends a signed resumable snapshot to Catora.

## Five-minute setup

### 1. Receive the source credentials

A Catora operator creates a **Catalog Bridge** source and provides these values through an approved secret channel:

```text
CATORA_BRIDGE_ENDPOINT=https://api.catora.codistan.org
CATORA_BRIDGE_SOURCE_ID=<source UUID>
CATORA_BRIDGE_TOKEN=<one-time source token>
```

The token is shown only when the source is created or rotated. Do not commit it or place it in browser-visible environment variables.

### 2. Add `catora.bridge.mjs`

```js
import "./src/database/connect.js";
import Product from "./src/models/Product.js";

export default {
  model: Product,
  endpoint: process.env.CATORA_BRIDGE_ENDPOINT,
  sourceId: process.env.CATORA_BRIDGE_SOURCE_ID,
  token: process.env.CATORA_BRIDGE_TOKEN,
  sourceLabel: "Production catalog",
};
```

The automatic mapper recognizes common fields such as:

- `_id`, `id`, `productId`
- `name`, `title`
- `description`, `body`, `details`
- `images`, `media`, `gallery`
- `variants`, `productVariants`, `skus`
- `attributes`, `specifications`, `specs`
- `brand`, `vendor`, `manufacturer`
- `categories`, `collections`, `tags`
- `seo`, `seoTitle`, `seoDescription`
- `createdAt`, `updatedAt`

### 3. Validate without sending data

```bash
npx catora-bridge catora.bridge.mjs --dry-run
```

### 4. Send the snapshot

```bash
npx catora-bridge catora.bridge.mjs
```

The default checkpoint is stored at `.catora/bridge-checkpoint.json`, allowing an interrupted upload to resume from the last accepted batch.

## Unusual schemas

Override only the fields that differ:

```js
export default {
  model: Product,
  endpoint: process.env.CATORA_BRIDGE_ENDPOINT,
  sourceId: process.env.CATORA_BRIDGE_SOURCE_ID,
  token: process.env.CATORA_BRIDGE_TOKEN,
  fields: {
    id: "productKey",
    title: "copy.heading",
    description: (product) => product.copy.longDescription,
    variants: "inventory.skus",
    images: ["assets.gallery", "images"],
  },
};
```

For a genuinely custom transformation, retain the inferred values and change only what is required:

```js
export default {
  model: Product,
  endpoint: process.env.CATORA_BRIDGE_ENDPOINT,
  sourceId: process.env.CATORA_BRIDGE_SOURCE_ID,
  token: process.env.CATORA_BRIDGE_TOKEN,
  mapProduct(product, inferred) {
    return {
      ...inferred,
      productType: product.taxonomy?.leaf,
      attributes: {
        ...inferred.attributes,
        warranty: product.commercial?.warrantyLabel,
      },
    };
  },
};
```

## Optional query controls

```js
export default {
  model: Product,
  filter: { deletedAt: null },
  cursorField: "_id",
  pageSize: 250,
  // credentials...
};
```

The cursor field must be present, stable, sortable and unique enough for deterministic pagination. MongoDB ObjectIDs work with the default `_id` cursor.

## Security boundary

The bridge:

- runs only in the project backend;
- never sends the MongoDB URI to Catora;
- performs no database or storefront writes;
- excludes customers, orders, payments, addresses, passwords, sessions and tokens;
- does not serialize entire MongoDB documents;
- signs every request with HMAC-SHA256;
- checks body hashes, timestamps and replay-resistant idempotency keys;
- stores batches encrypted at rest through Catora object storage;
- uses one revocable credential per Catora source.

Do not import this package into a Next.js client component or expose its token through `NEXT_PUBLIC_*` variables.

## Production operation

A bridge failure must not affect commerce traffic. Run exports from a worker, protected internal job or deployment command rather than from a customer request.

A first integration should use complete snapshots. Scheduled and incremental synchronization remains gated until the production diagnostic demonstrates commercial value.
