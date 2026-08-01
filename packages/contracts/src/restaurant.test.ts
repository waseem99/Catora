import { describe, expect, it } from "vitest";

import {
  RESTAURANT_DOMAIN_VERSION,
  RestaurantFactSchema,
  RestaurantFreshnessPolicySchema,
  RestaurantSnapshotSchema,
} from "./restaurant";

const observedAt = "2026-08-01T12:00:00Z";

function snapshot() {
  return {
    version: RESTAURANT_DOMAIN_VERSION,
    sourceId: "00000000-0000-4000-8000-000000000001",
    snapshotId: "00000000-0000-4000-8000-000000000002",
    observedAt,
    brands: [
      {
        version: RESTAURANT_DOMAIN_VERSION,
        canonicalKey: "brand:north-grill:1234567890abcdef1234",
        name: "North Grill",
        locations: [
          {
            canonicalKey: "location:north-grill-lahore:1234567890abcdef1234",
            externalLocationId: "lahore-01",
            name: "North Grill Lahore",
            address: {
              streetAddress: "1 Main Road",
              addressLocality: "Lahore",
              addressCountry: "PK",
            },
            geo: { latitude: 31.5204, longitude: 74.3587 },
            serviceModes: ["dine_in", "takeaway", "delivery"],
            menus: [
              {
                canonicalKey: "menu:north-grill-lahore-main:1234567890abcdef1234",
                name: "Main Menu",
                currency: "PKR",
                sections: [
                  {
                    canonicalKey: "menu-section:burgers:1234567890abcdef1234",
                    name: "Burgers",
                    items: [
                      {
                        canonicalKey: "menu-item:signature:1234567890abcdef1234",
                        name: "Signature Burger",
                        priceAmount: "799.00",
                        currency: "PKR",
                        availabilityState: "available",
                        dietaryFacts: { halal: "verified" },
                        allergenFacts: { contains: ["wheat", "milk"] },
                        modifiers: [
                          {
                            canonicalKey: "modifier-group:cheese:1234567890abcdef1234",
                            name: "Cheese",
                            options: [
                              {
                                canonicalKey:
                                  "modifier-option:cheddar:1234567890abcdef1234",
                                name: "Cheddar",
                                priceDelta: "100.00",
                                currency: "PKR",
                                availabilityState: "available",
                              },
                            ],
                          },
                        ],
                      },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  } as const;
}

describe("restaurant contracts", () => {
  it("accepts a bounded multi-location restaurant snapshot", () => {
    expect(RestaurantSnapshotSchema.parse(snapshot()).brands).toHaveLength(1);
  });

  it("rejects supported facts without evidence-backed values", () => {
    expect(() =>
      RestaurantFactSchema.parse({
        key: "halal",
        value: null,
        valueType: "boolean",
        state: "supported",
        sourceRecordId: "00000000-0000-4000-8000-000000000003",
        fieldPath: "$.halal",
        observedAt,
        checksum: "a".repeat(64),
      }),
    ).toThrow(/require a value/);
  });

  it("rejects freshness policies with inverted ages", () => {
    expect(() =>
      RestaurantFreshnessPolicySchema.parse({
        entityType: "menu_item",
        factKey: "price",
        warningAgeSeconds: 7200,
        maxAgeSeconds: 3600,
        policyVersion: "price/v1",
      }),
    ).toThrow(/must exceed/);
  });

  it("rejects unknown and transaction-like fields", () => {
    expect(() =>
      RestaurantSnapshotSchema.parse({
        ...snapshot(),
        customerOrders: [],
      }),
    ).toThrow();
  });
});
