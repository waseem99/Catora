import { describe, expect, it, vi } from "vitest";
import { fetchApiHealth } from "./api";

describe("fetchApiHealth", () => {
  it("validates the API contract", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: "ok", service: "catora-api", version: "0.1.0" }), { status: 200 }));
    await expect(fetchApiHealth(fetcher as typeof fetch)).resolves.toEqual({ status: "ok", service: "catora-api", version: "0.1.0" });
  });

  it("rejects malformed health responses", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: "unknown" }), { status: 200 }));
    await expect(fetchApiHealth(fetcher as typeof fetch)).rejects.toThrow();
  });
});
