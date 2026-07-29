import { describe, expect, it } from "vitest";
import {
  ServiceVisibilityProvisionSchema,
  ServiceVisibilityRunSchema,
  ServiceVisibilitySourceSchema,
  serviceVisibilityArtifactUrl,
} from "./service-visibility";

const workspaceId = "69a61f39-8c42-4a5b-9290-0c62455f1904";
const sourceId = "ba0cb933-12e4-4e6f-ae21-306694b02880";
const reportId = "59e86531-299b-4f3d-b184-e9740da5bd22";

const source = {
  id: sourceId,
  workspace_id: workspaceId,
  name: "Authorized WordPress service site",
  site_url: "https://example.com",
  connection_mode: "wordpress_bridge" as const,
  status: "ready",
  monitoring_enabled: false,
  token_fingerprint: "abc123def456",
  created_at: "2026-07-29T06:00:00Z",
  updated_at: "2026-07-29T06:00:00Z",
};

describe("service visibility contracts", () => {
  it("parses source and one-time provisioning responses", () => {
    expect(ServiceVisibilitySourceSchema.parse(source).connection_mode).toBe(
      "wordpress_bridge",
    );
    expect(
      ServiceVisibilityProvisionSchema.parse({
        ...source,
        endpoint: "https://api.catora.codistan.org",
        token: "one-time-token",
      }).token,
    ).toBe("one-time-token");
  });

  it("parses evidence-backed completed runs", () => {
    const run = ServiceVisibilityRunSchema.parse({
      id: reportId,
      workspace_id: workspaceId,
      source_id: sourceId,
      ingestion_job_id: "ebfd5890-652f-4de2-836a-b65818e461cf",
      status: "completed",
      scorecard: { overall: 74, technical_seo: 82 },
      page_count: 42,
      finding_count: 17,
      question_count: 25,
      continuity: { new_findings: 4, resolved_findings: 2 },
      artifacts: ["service_visibility_findings_csv"],
      error: null,
      created_at: "2026-07-29T06:00:00Z",
      updated_at: "2026-07-29T06:04:00Z",
    });
    expect(run.question_count).toBe(25);
    expect(run.scorecard.overall).toBe(74);
  });

  it("builds a workspace-scoped artifact URL", () => {
    expect(
      serviceVisibilityArtifactUrl(
        workspaceId,
        reportId,
        "service_visibility_findings_csv",
      ),
    ).toContain(
      `/api/v1/workspaces/${workspaceId}/service-visibility/runs/${reportId}/artifacts/service_visibility_findings_csv`,
    );
  });
});
