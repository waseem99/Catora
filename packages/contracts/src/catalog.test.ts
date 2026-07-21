import { describe, expect, it } from "vitest";

import {
  ProductDetailSchema,
  ProductListResponseSchema,
  ProductProvenanceResponseSchema,
} from "./catalog";

const productId = "11111111-1111-4111-8111-111111111111";
const workspaceId = "22222222-2222-4222-8222-222222222222";
const variantId = "33333333-3333-4333-8333-333333333333";
const attributeId = "44444444-4444-4444-8444-444444444444";
const imageId = "55555555-5555-4555-8555-555555555555";
const sourceRecordId = "66666666-6666-4666-8666-666666666666";
const sourceId = "77777777-7777-4777-8777-777777777777";
const evidenceId = "88888888-8888-4888-8888-888888888888";
const timestamp = "2026-07-21T12:00:00Z";

const attribute = {
  id: attributeId,
  variant_id: null,
  key: "weight",
  value: {
    raw: "2 kg",
    canonical_value: "2000",
    canonical_unit: "g",
  },
  value_type: "measurement",
  unit: "g",
  locale: null,
  value_state: "present",
  transformer_version: "catalog-normalizer-v2",
  confidence: "high",
  created_at: timestamp,
  updated_at: timestamp,
};

describe("catalog response contracts", () => {
  it("parses list and detail responses with typed values", () => {
    expect(
      ProductListResponseSchema.parse({
        items: [
          {
            id: productId,
            canonical_key: "source:test:product:1",
            title: "Cloud Sofa",
            primary_category_id: null,
            status: "active",
            variant_count: 1,
            attribute_count: 1,
            image_count: 1,
            warning_count: 0,
            created_at: timestamp,
            updated_at: timestamp,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      }).total,
    ).toBe(1);

    const detail = ProductDetailSchema.parse({
      id: productId,
      workspace_id: workspaceId,
      canonical_key: "source:test:product:1",
      title: "Cloud Sofa",
      primary_category_id: null,
      status: "active",
      product_attributes: [attribute],
      product_images: [],
      variants: [
        {
          id: variantId,
          canonical_key: "source:test:variant:1",
          sku: "SOFA-BLUE",
          title: "Blue",
          option_values: { Color: "Blue" },
          is_retired: false,
          attributes: [],
          images: [
            {
              id: imageId,
              variant_id: variantId,
              url: "https://example.com/blue.jpg",
              alt_text: "Blue sofa",
              position: 0,
              checksum: null,
              created_at: timestamp,
              updated_at: timestamp,
            },
          ],
          created_at: timestamp,
          updated_at: timestamp,
        },
      ],
      warning_count: 0,
      provenance_count: 1,
      created_at: timestamp,
      updated_at: timestamp,
    });

    expect(detail.product_attributes[0]?.unit).toBe("g");
    expect(detail.variants[0]?.sku).toBe("SOFA-BLUE");
  });

  it("accepts evidence metadata but rejects raw source payloads", () => {
    const provenance = {
      product_id: productId,
      items: [
        {
          id: evidenceId,
          source_record_id: sourceRecordId,
          catalog_source_id: sourceId,
          catalog_source_name: "Primary Shopify",
          source_type: "shopify",
          external_id: "gid://shopify/Product/1",
          source_updated_at: timestamp,
          snapshot_at: timestamp,
          product_id: productId,
          variant_id: null,
          attribute_id: attributeId,
          attribute_key: "weight",
          field_path: "product.metafields.weight",
          excerpt: "2 kg",
          checksum: "a".repeat(64),
          created_at: timestamp,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    };

    expect(ProductProvenanceResponseSchema.parse(provenance).items).toHaveLength(1);
    expect(
      ProductProvenanceResponseSchema.safeParse({
        ...provenance,
        items: [{ ...provenance.items[0], payload: { token: "secret" } }],
      }).success,
    ).toBe(false);
  });
});
