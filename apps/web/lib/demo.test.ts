import { describe, expect, it } from "vitest";
import {
  DemoPreflightSchema,
  DemoResetStatusSchema,
  demoPreflightPath,
  demoResetStatusPath,
  formatBasisPoints,
  humanizeStatus,
} from "./demo";

describe("demo formatting", () => {
  it("formats deterministic basis points", () => {
    expect(formatBasisPoints(6840)).toBe("68.4%");
  });

  it("humanizes persisted states", () => {
    expect(humanizeStatus("possible_match_missing_data")).toBe("possible match missing data");
  });
});

describe("presenter reliability contracts", () => {
  it("builds workspace-scoped preflight and reset status paths", () => {
    expect(demoPreflightPath("workspace-id")).toBe(
      "/api/v1/workspaces/workspace-id/demo/preflight",
    );
    expect(demoResetStatusPath("workspace-id", "task-id")).toBe(
      "/api/v1/workspaces/workspace-id/demo/reset/task-id",
    );
  });

  it("parses a timestamped verified fallback snapshot", () => {
    const parsed = DemoPreflightSchema.parse({
      workspace_id: "4ea8faf2-12fd-4a29-8aa0-2ecbfb66aeaf",
      generated_at: "2026-07-23T06:00:00Z",
      ready: false,
      components: [
        {
          key: "worker",
          label: "Background worker",
          state: "error",
          detail: "Unavailable (RuntimeError)",
        },
      ],
      last_verified_snapshot: {
        audit_run_id: "9c784eef-47e1-43aa-a390-daeb8a348965",
        source_snapshot_hash: "a".repeat(64),
        verified_at: "2026-07-23T05:55:00Z",
        product_count: 1_000,
        variant_count: 2_000,
        finding_count: 387,
        recommendation_field_count: 3,
      },
    });
    expect(parsed.last_verified_snapshot.variant_count).toBe(2_000);
  });

  it("parses sanitized reset failure status", () => {
    const parsed = DemoResetStatusSchema.parse({
      task_id: "91fcbfdd-7aa6-48f5-8888-b72e5d08fdd7",
      status: "failed",
      detail: "The previous verified snapshot remains available",
    });
    expect(parsed.status).toBe("failed");
  });
});
