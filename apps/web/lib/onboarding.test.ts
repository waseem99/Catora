import { describe, expect, it } from "vitest";
import { IngestionJobSchema, normalizationSummary } from "./onboarding";

const job = {
  id: "59e86531-299b-4f3d-b184-e9740da5bd22",
  workspace_id: "69a61f39-8c42-4a5b-9290-0c62455f1904",
  catalog_source_id: "ebfd5890-652f-4de2-836a-b65818e461cf",
  status: "completed" as const,
  processed_count: 2,
  success_count: 2,
  rejection_count: 0,
  warning_count: 0,
  checkpoint: {
    row: 2,
    normalization: {
      products_created: 1,
      variants_created: 2,
    },
  },
  started_at: "2026-07-23T07:00:00Z",
  completed_at: "2026-07-23T07:01:00Z",
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T07:01:00Z",
};

describe("catalog onboarding contracts", () => {
  it("parses a completed persisted ingestion job", () => {
    const parsed = IngestionJobSchema.parse(job);
    expect(parsed.success_count).toBe(2);
  });

  it("returns only an object normalization summary", () => {
    const parsed = IngestionJobSchema.parse(job);
    expect(normalizationSummary(parsed)).toEqual({
      products_created: 1,
      variants_created: 2,
    });
  });

  it("does not claim normalization when the checkpoint is absent", () => {
    const parsed = IngestionJobSchema.parse({ ...job, checkpoint: { row: 2 } });
    expect(normalizationSummary(parsed)).toBeNull();
  });
});
