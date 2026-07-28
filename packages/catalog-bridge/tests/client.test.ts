import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  CatalogBridgeClient,
  canonicalJson,
  sha256,
  signCatalogBridgeRequest,
  type CatalogBridgeCheckpoint,
  type CatalogBridgeCheckpointStore,
} from "../src/client.js";

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

describe("catalog bridge client", () => {
  it("uses deterministic JSON and the documented HMAC canonical request", () => {
    const body = canonicalJson({ z: 1, a: { y: true, x: "value" } });
    expect(body).toBe('{"a":{"x":"value","y":true},"z":1}');
    const signature = signCatalogBridgeRequest({
      method: "PUT",
      path: "/bridge",
      timestamp: "123",
      contentSha256: sha256(body),
      idempotencyKey: "snapshot:batch:0",
      token: "secret",
    });
    const expected = createHmac("sha256", "secret")
      .update(`PUT\n/bridge\n123\n${sha256(body)}\nsnapshot:batch:0`)
      .digest("base64url");
    expect(signature).toBe(expected);
  });

  it("uploads a bounded snapshot and clears its checkpoint", async () => {
    const requests: Array<{ url: string; method: string; body: string }> = [];
    const checkpoint = new MemoryCheckpointStore();
    const fetchImplementation: typeof fetch = async (input, init) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? init.body : "";
      requests.push({ url, method: init?.method ?? "GET", body });
      const snapshotId = JSON.parse(body || "{}").snapshotId ??
        url.split("/snapshots/")[1]?.split("/")[0];
      return new Response(
        JSON.stringify({
          sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
          snapshotId,
          status: url.endsWith("/complete") ? "queued" : "receiving",
          acceptedBatches: url.includes("/batches/") ? 1 : 0,
          acceptedProducts: url.includes("/batches/") ? 2 : 0,
          acceptedVariants: url.includes("/batches/") ? 1 : 0,
          ingestionJobId: url.endsWith("/complete")
            ? "a91f7d26-2077-42cc-b530-9147d3e4ec0a"
            : null,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
    const client = new CatalogBridgeClient({
      endpoint: "https://api.example.com",
      sourceId: "c29fc752-3834-4983-92a5-e6f516a830cc",
      token: "a".repeat(48),
      batchSize: 2,
      fetchImplementation,
      checkpointStore: checkpoint,
    });

    const result = await client.uploadSnapshot({
      snapshotId: "64de9775-59d0-4141-b8c8-c90e74c9f9f0",
      productCount: 2,
      variantCount: 1,
      products: [
        { id: "p1", title: "Chair", variants: [{ id: "v1" }] },
        { id: "p2", title: "Table" },
      ],
    });

    expect(requests.map((request) => request.method)).toEqual([
      "POST",
      "PUT",
      "POST",
    ]);
    expect(result.status).toBe("queued");
    expect(checkpoint.value).toBeNull();
  });
});
