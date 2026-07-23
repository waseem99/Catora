import { z } from "zod";

const uuid = z.string().uuid();
const evidenceSchema = z.record(z.string(), z.unknown());

export const DemoOverviewSchema = z.object({
  workspace_id: uuid,
  workspace_name: z.string(),
  generated_at: z.string(),
  catalog: z.object({
    product_count: z.number().int().nonnegative(),
    variant_count: z.number().int().nonnegative(),
    attribute_count: z.number().int().nonnegative(),
    image_count: z.number().int().nonnegative(),
  }),
  audit: z.object({
    run_id: uuid,
    score_basis_points: z.number().int().min(0).max(10_000),
    confidence_basis_points: z.number().int().min(0).max(10_000),
    critical_count: z.number().int().nonnegative(),
    high_count: z.number().int().nonnegative(),
    medium_count: z.number().int().nonnegative(),
  }),
  top_gaps: z.array(z.object({
    field_key: z.string(),
    label: z.string(),
    affected_products: z.number().int().nonnegative(),
  })),
  hero_product: z.object({
    id: uuid,
    title: z.string(),
    canonical_key: z.string(),
    category_key: z.string(),
    source_evidence: z.array(z.object({
      field_path: z.string(),
      excerpt: z.string().nullable(),
      source_label: z.string(),
    })),
  }),
  findings: z.array(z.object({
    id: uuid,
    product_id: uuid,
    product_title: z.string(),
    severity: z.enum(["critical", "high", "medium", "low", "informational"]),
    title: z.string(),
    explanation: z.string(),
    category_key: z.string(),
    field_key: z.string(),
    business_impact: z.string(),
    remediation_type: z.string(),
    evidence: z.array(evidenceSchema),
  })),
  intent: z.object({
    id: uuid,
    name: z.string(),
    query: z.string(),
    confident_match_count: z.number().int().nonnegative(),
    possible_match_count: z.number().int().nonnegative(),
    non_match_count: z.number().int().nonnegative(),
    insufficient_category_count: z.number().int().nonnegative(),
    hero_product_before_status: z.string(),
    hero_product_after_status: z.string(),
    missing_fields: z.array(z.string()),
    explanation: z.string(),
  }),
  recommendation: z.object({
    id: uuid,
    product_id: uuid,
    product_title: z.string(),
    status: z.string(),
    source_snapshot_hash: z.string().length(64),
    fields: z.array(z.object({
      id: uuid,
      field_key: z.string(),
      label: z.string(),
      original_value: z.unknown().nullable(),
      proposed_value: z.unknown().nullable(),
      edited_value: z.unknown().nullable(),
      confidence: z.string(),
      requires_verification: z.boolean(),
      evidence: z.array(evidenceSchema),
      decision: z.enum(["approved", "rejected"]).nullable(),
      decision_comment: z.string().nullable(),
    })),
  }),
  change_set: z.object({
    id: uuid.nullable(),
    name: z.string().nullable(),
    status: z.string(),
    approved_field_count: z.number().int().nonnegative(),
    rejected_field_count: z.number().int().nonnegative(),
    export_ready: z.boolean(),
  }),
  report_pptx_path: z.string(),
  operational_csv_path: z.string(),
});

export const DemoPreflightSchema = z.object({
  workspace_id: uuid,
  generated_at: z.string(),
  ready: z.boolean(),
  components: z.array(z.object({
    key: z.string(),
    label: z.string(),
    state: z.enum(["ok", "warning", "error"]),
    detail: z.string(),
  })),
  last_verified_snapshot: z.object({
    audit_run_id: uuid,
    source_snapshot_hash: z.string().length(64),
    verified_at: z.string(),
    product_count: z.number().int().nonnegative(),
    variant_count: z.number().int().nonnegative(),
    finding_count: z.number().int().nonnegative(),
    recommendation_field_count: z.number().int().nonnegative(),
  }),
});

export const DemoResetResponseSchema = z.object({
  task_id: uuid,
  status: z.enum(["queued", "running", "completed", "failed"]),
});

export const DemoResetStatusSchema = DemoResetResponseSchema.extend({
  detail: z.string(),
});

export type DemoOverview = z.infer<typeof DemoOverviewSchema>;
export type DemoPreflight = z.infer<typeof DemoPreflightSchema>;
export type DemoResetStatus = z.infer<typeof DemoResetStatusSchema>;
export type DemoDecision = "approved" | "rejected";

export function demoOverviewPath(workspaceId: string): string {
  return `/api/v1/workspaces/${workspaceId}/demo`;
}

export function demoDecisionPath(workspaceId: string, recommendationId: string): string {
  return `${demoOverviewPath(workspaceId)}/recommendations/${recommendationId}/decision`;
}

export function demoPreflightPath(workspaceId: string): string {
  return `${demoOverviewPath(workspaceId)}/preflight`;
}

export function demoResetPath(workspaceId: string): string {
  return `${demoOverviewPath(workspaceId)}/reset`;
}

export function demoResetStatusPath(workspaceId: string, taskId: string): string {
  return `${demoResetPath(workspaceId)}/${taskId}`;
}

export function absoluteApiPath(path: string): string {
  const base = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

export function formatBasisPoints(value: number): string {
  return `${(value / 100).toFixed(1)}%`;
}

export function humanizeStatus(value: string): string {
  return value.replaceAll("_", " ");
}
