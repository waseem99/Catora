import { describe, expect, it } from "vitest";
import {
  DiagnosticSchema,
  diagnosticStageState,
} from "./diagnostics";

const diagnostic = {
  id: "59e86531-299b-4f3d-b184-e9740da5bd22",
  workspace_id: "69a61f39-8c42-4a5b-9290-0c62455f1904",
  organization_id: "ebfd5890-652f-4de2-836a-b65818e461cf",
  company_name: "Lama Furniture",
  status: "auditing" as const,
  current_stage: "Running deterministic audit",
  detail: "Evidence-backed catalog requirements are being evaluated.",
  market_code: "AE",
  locale: "en-AE",
  currency: "AED",
  retention_expires_at: "2026-08-22T07:00:00Z",
  counts: {
    processed_rows: 2000,
    accepted_rows: 1998,
    rejected_rows: 2,
    warning_count: 7,
    product_count: 1000,
    variant_count: 2000,
    assigned_category_count: 950,
    ambiguous_category_count: 30,
    unclassified_category_count: 20,
    finding_count: 387,
    intent_run_count: 0,
    intent_match_count: 0,
  },
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T07:04:00Z",
  completed_at: null,
  failure_code: null,
  failure_detail: null,
  ingestion_job_id: "ba0cb933-12e4-4e6f-ae21-306694b02880",
  audit_run_id: "77d3ddfe-3c35-4915-9642-31995dad1b15",
  intent_run_ids: [],
  result_path:
    "/workspace/69a61f39-8c42-4a5b-9290-0c62455f1904/diagnostic/59e86531-299b-4f3d-b184-e9740da5bd22",
  report_path:
    "/api/v1/prospect-diagnostics/59e86531-299b-4f3d-b184-e9740da5bd22/report.pptx",
  backlog_path:
    "/api/v1/prospect-diagnostics/59e86531-299b-4f3d-b184-e9740da5bd22/backlog.csv",
  rejection_path:
    "/api/v1/prospect-diagnostics/59e86531-299b-4f3d-b184-e9740da5bd22/rejections",
};

describe("prospect diagnostic contracts", () => {
  it("parses reconciled persisted counts", () => {
    const parsed = DiagnosticSchema.parse(diagnostic);
    expect(parsed.counts.variant_count).toBe(2000);
    expect(parsed.status).toBe("auditing");
  });

  it("marks only proven earlier stages complete", () => {
    expect(diagnosticStageState("auditing", "normalizing")).toBe("completed");
    expect(diagnosticStageState("auditing", "auditing")).toBe("active");
    expect(diagnosticStageState("auditing", "matching")).toBe("pending");
  });

  it("marks the pipeline failed without inventing later completion", () => {
    expect(diagnosticStageState("failed", "queued")).toBe("failed");
    expect(diagnosticStageState("failed", "preparing_reports")).toBe("failed");
  });
});
