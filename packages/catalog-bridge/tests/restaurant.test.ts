import { describe, expect, it } from "vitest";

import {
  RestaurantCatalogBridgeClient,
  type CatalogBridgeCheckpoint,
  type CatalogBridgeCheckpointStore,
} from "../src/index.js";
import {
  inspectMongoRestaurant,
  mongoRestaurantBrands,
} from "../src/restaurant-mongo.js";

class MemoryCheckpointStore implements CatalogBridgeCheckpointStore {
  value: CatalogBridgeCheckpoint | null = null;

  async load(): Promise<CatalogBridgeCheckpoint | null> {
    return this.value;
  }

  async save(checkpoint: CatalogBridgeCheckpoint): Promise<void> {
    this.value = checkpoint;
  }

  async clear(): Promise<void> {
    this.value = null;
  }
}

function brand() {
  return {
    recordType: "restaurant_brand" as const,
    id: "brand-1",
    name: "North Grill",
    locations: [
      {
        id: "location-1",
        name: "North Grill Lahore",
        address: { addressLocality: "Lahore", addressCountry: "PK" },
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
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  };
}

describe("restaurant bridge client", () => {
  it("uploads reconciled counts and clears the resumable checkpoint", async () => {
    const requests: Array<{ url: string; method: string; body: string }> = [];
    const checkpoint = new MemoryCheckpointStore();
    const fetchImplementation: typeof fetch = async (input, init) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? init.body : "";
      requests.push({ url, method: init?.method ?? "GET", body });
      const parsed = JSON.parse(body || "{}");
      const snapshotId =
        parsed.snapshotId ?? url.split("/snapshots/")[1]?.split("/")[0];
      return new Response(
        JSON.stringify({
          sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
          snapshotId,
          profile: "restaurant/v1",
          status: url.endsWith("/complete") ? "queued" : "receiving",
          acceptedBatches: url.includes("/batches/") ? 1 : 0,
          acceptedBrands: url.includes("/batches/") ? 1 : 0,
          acceptedLocations: url.includes("/batches/") ? 1 : 0,
          acceptedMenuItems: url.includes("/batches/") ? 1 : 0,
          ingestionJobId: url.endsWith("/complete")
            ? "a91f7d26-2077-42cc-b530-9147d3e4ec0a"
            : null,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
    const client = new RestaurantCatalogBridgeClient({
      endpoint: "https://api.example.com",
      sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
      token: "a".repeat(48),
      batchSize: 1,
      fetchImplementation,
      checkpointStore: checkpoint,
    });

    const result = await client.uploadSnapshot({
      snapshotId: "64de9775-59d0-4141-b8c8-c90e74c9f9f0",
      brandCount: 1,
      locationCount: 1,
      menuItemCount: 1,
      brands: [brand()],
    });

    expect(requests.map((request) => request.method)).toEqual([
      "POST",
      "PUT",
      "POST",
    ]);
    expect(JSON.parse(requests[0]!.body)).toMatchObject({
      profile: "restaurant/v1",
      declaredBrandCount: 1,
      declaredLocationCount: 1,
      declaredMenuItemCount: 1,
    });
    expect(result.status).toBe("queued");
    expect(checkpoint.value).toBeNull();
  });

  it("fails before completion when declared nested counts do not reconcile", async () => {
    const fetchImplementation: typeof fetch = async (input, init) => {
      const body = typeof init?.body === "string" ? init.body : "";
      const snapshotId = JSON.parse(body || "{}").snapshotId;
      return new Response(
        JSON.stringify({
          sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
          snapshotId,
          profile: "restaurant/v1",
          status: "receiving",
          acceptedBatches: 0,
          acceptedBrands: 0,
          acceptedLocations: 0,
          acceptedMenuItems: 0,
          ingestionJobId: null,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
    const client = new RestaurantCatalogBridgeClient({
      endpoint: "https://api.example.com",
      sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
      token: "a".repeat(48),
      fetchImplementation,
    });

    await expect(
      client.uploadSnapshot({
        brandCount: 1,
        locationCount: 2,
        menuItemCount: 1,
        brands: [brand()],
      }),
    ).rejects.toThrow(/Declared 2 locations but mapped 1/);
  });
});

describe("explicit Mongo restaurant mapper", () => {
  it("uses stable cursor pagination and a required explicit mapper", async () => {
    const documents = [
      { _id: "1", name: "North Grill" },
      { _id: "2", name: "South Grill" },
    ];
    const model = {
      find: (filter: Record<string, unknown> = {}) => {
        const and = Array.isArray(filter.$and) ? filter.$and : [];
        const cursor = (and[1] as { _id?: { $gt?: string } } | undefined)?._id?.$gt;
        const rows = cursor
          ? documents.filter((document) => document._id > cursor)
          : documents;
        const query = {
          sort: () => query,
          limit: (limit: number) => {
            rows.splice(limit);
            return query;
          },
          lean: () => query,
          exec: async () => rows,
        };
        return query;
      },
    };
    const options = {
      model,
      pageSize: 1,
      mapBrand: (document: (typeof documents)[number]) => ({
        ...brand(),
        id: `brand-${document._id}`,
        name: document.name,
        locations: [
          {
            ...brand().locations[0],
            id: `location-${document._id}`,
            name: `${document.name} Lahore`,
          },
        ],
      }),
    };

    const mapped = [await Array.fromAsync(mongoRestaurantBrands(options))];
    const inspection = await inspectMongoRestaurant(options);

    expect(mapped[0]).toHaveLength(2);
    expect(inspection).toMatchObject({
      brandCount: 2,
      locationCount: 2,
      menuItemCount: 2,
      invalidCount: 0,
    });
  });
});
