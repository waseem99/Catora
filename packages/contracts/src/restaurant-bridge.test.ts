import { describe, expect, it } from "vitest";

import {
  CATALOG_BRIDGE_PROTOCOL_VERSION,
  RESTAURANT_BRIDGE_PROFILE,
  RestaurantBridgeBatchSchema,
  RestaurantBridgeBrandSchema,
  RestaurantBridgeSnapshotManifestSchema,
} from "./index";

function brand() {
  return {
    recordType: "restaurant_brand" as const,
    id: "brand-1",
    name: "North Grill",
    locations: [
      {
        id: "location-1",
        name: "North Grill Lahore",
        address: {
          streetAddress: "1 Main Road",
          addressLocality: "Lahore",
          addressCountry: "PK",
        },
        serviceModes: ["dine_in", "takeaway", "delivery"] as const,
        menus: [
          {
            id: "menu-1",
            name: "Main Menu",
            currency: "PKR",
            sections: [
              {
                id: "section-1",
                name: "Burgers",
                items: [
                  {
                    id: "item-1",
                    name: "Signature Burger",
                    price: 799,
                    currency: "PKR",
                    availability: "available" as const,
                    dietaryFacts: { halal: "verified" },
                    allergenFacts: { contains: ["wheat", "milk"] },
                    modifiers: [
                      {
                        id: "group-1",
                        name: "Cheese",
                        options: [
                          {
                            id: "option-1",
                            name: "Cheddar",
                            priceDelta: 100,
                            currency: "PKR",
                            availability: "available" as const,
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
    offers: [
      {
        id: "offer-1",
        name: "Weekday Meal",
        locationIds: ["location-1"],
        status: "active" as const,
      },
    ],
  };
}

describe("restaurant bridge profile", () => {
  it("accepts a versioned brand/location/menu snapshot", () => {
    const parsed = RestaurantBridgeBatchSchema.parse({
      protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
      profile: RESTAURANT_BRIDGE_PROFILE,
      snapshotId: "00000000-0000-4000-8000-000000000001",
      sequence: 0,
      records: [brand()],
    });
    expect(parsed.records[0]?.locations[0]?.menus[0]?.sections[0]?.items).toHaveLength(
      1,
    );
  });

  it("permits explicit public branch addresses", () => {
    const parsed = RestaurantBridgeBrandSchema.parse(brand());
    expect(parsed.locations[0]?.address.addressLocality).toBe("Lahore");
  });

  it.each([
    { customerToken: "secret" },
    { orders: [{ id: "order-1" }] },
    { payment: { card: "not-allowed" } },
    { loyaltySession: "not-allowed" },
  ])("rejects restricted nested restaurant data", (restricted) => {
    const candidate = brand();
    const item = candidate.locations[0]!.menus[0]!.sections[0]!.items[0]!;
    (item as { dietaryFacts: unknown }).dietaryFacts = restricted;
    expect(() => RestaurantBridgeBrandSchema.parse(candidate)).toThrow();
  });

  it("rejects unknown top-level transactional fields", () => {
    expect(() =>
      RestaurantBridgeBrandSchema.parse({
        ...brand(),
        customerOrders: [],
      }),
    ).toThrow();
  });

  it("requires explicit reconciled snapshot counts", () => {
    expect(() =>
      RestaurantBridgeSnapshotManifestSchema.parse({
        protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
        profile: RESTAURANT_BRIDGE_PROFILE,
        snapshotId: "00000000-0000-4000-8000-000000000001",
        startedAt: "2026-08-01T12:00:00Z",
        declaredBrandCount: 1,
        declaredLocationCount: -1,
        declaredMenuItemCount: 1,
      }),
    ).toThrow();
  });
});
