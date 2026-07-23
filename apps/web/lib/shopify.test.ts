import { describe, expect, it } from "vitest";
import {
  ShopifyConfigurationSchema,
  ShopifyInstallationSchema,
} from "./shopify";

describe("Shopify installation contracts", () => {
  it("parses the minimum read-only configuration", () => {
    expect(
      ShopifyConfigurationSchema.parse({
        enabled: true,
        required_scopes: ["read_products"],
        callback_url:
          "https://api.catora.codistan.org/api/v1/shopify/oauth/callback",
      }),
    ).toEqual({
      enabled: true,
      required_scopes: ["read_products"],
      callback_url:
        "https://api.catora.codistan.org/api/v1/shopify/oauth/callback",
    });
  });

  it("parses connection and synchronized catalog health without credentials", () => {
    const installation = ShopifyInstallationSchema.parse({
      id: "59e86531-299b-4f3d-b184-e9740da5bd22",
      workspace_id: "69a61f39-8c42-4a5b-9290-0c62455f1904",
      catalog_source_id: "ba0cb933-12e4-4e6f-ae21-306694b02880",
      shop_domain: "northstar-living-demo.myshopify.com",
      status: "active",
      granted_scopes: ["read_products"],
      token_mode: "expiring_offline",
      access_token_expires_at: "2026-07-23T08:00:00Z",
      refresh_token_expires_at: "2026-10-21T08:00:00Z",
      installed_at: "2026-07-23T07:00:00Z",
      refreshed_at: "2026-07-23T07:00:00Z",
      disconnected_at: null,
      last_health_checked_at: null,
      health: "healthy",
      detail: "Catora can resolve a protected Shopify catalog credential.",
      sync_status: "completed",
      last_successful_sync_at: "2026-07-23T07:15:00Z",
      last_sync_job_id: "7b1608dc-69ff-44d2-a014-08d09be8dbe9",
      last_audit_run_id: "6a453aa8-52ed-49e0-bb8f-307460a7beb4",
      product_count: 1000,
      variant_count: 2000,
      warning_count: 3,
      last_sync_error_type: null,
    });
    expect(installation.granted_scopes).toEqual(["read_products"]);
    expect(installation.product_count).toBe(1000);
    expect(installation.variant_count).toBe(2000);
    expect(installation).not.toHaveProperty("access_token");
    expect(installation).not.toHaveProperty("refresh_token");
  });
});
