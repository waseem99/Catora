"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/auth";
import {
  absoluteApiPath,
  demoDecisionPath,
  demoOverviewPath,
  DemoOverviewSchema,
  type DemoDecision,
  type DemoOverview,
  formatBasisPoints,
  humanizeStatus,
} from "@/lib/demo";

type Props = { workspaceId: string };
type DraftDecision = {
  decision?: DemoDecision;
  editedValue: string;
  verified: boolean;
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not supplied";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function severityClass(severity: string): string {
  return `severity-badge severity-${severity}`;
}

export function ClientDemo({ workspaceId }: Props) {
  const [overview, setOverview] = useState<DemoOverview | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftDecision>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiRequest<unknown>(demoOverviewPath(workspaceId));
      const parsed = DemoOverviewSchema.parse(payload);
      setOverview(parsed);
      setDrafts(
        Object.fromEntries(
          parsed.recommendation.fields.map((field) => [
            field.id,
            {
              decision: field.decision ?? undefined,
              editedValue: displayValue(field.edited_value ?? field.proposed_value),
              verified: !field.requires_verification,
            },
          ]),
        ),
      );
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Unable to load the client demo");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const allDecided = useMemo(() => {
    if (!overview) return false;
    return overview.recommendation.fields.every((field) => Boolean(drafts[field.id]?.decision));
  }, [drafts, overview]);

  function updateDraft(fieldId: string, patch: Partial<DraftDecision>) {
    setDrafts((current) => ({
      ...current,
      [fieldId]: {
        decision: current[fieldId]?.decision,
        editedValue: current[fieldId]?.editedValue ?? "",
        verified: current[fieldId]?.verified ?? false,
        ...patch,
      },
    }));
    setNotice(null);
  }

  async function submitDecisions() {
    if (!overview || !allDecided) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(
        demoDecisionPath(workspaceId, overview.recommendation.id),
        {
          method: "POST",
          body: JSON.stringify({
            expected_source_snapshot_hash: overview.recommendation.source_snapshot_hash,
            decisions: overview.recommendation.fields.map((field) => {
              const draft = drafts[field.id] ?? {
                decision: field.decision ?? undefined,
                editedValue: displayValue(field.edited_value ?? field.proposed_value),
                verified: !field.requires_verification,
              };
              const proposedIsNumber = typeof field.proposed_value === "number";
              const editedValue = proposedIsNumber
                ? Number(draft.editedValue)
                : draft.editedValue;
              return {
                field_id: field.id,
                decision: draft.decision,
                edited_value: editedValue,
                verified: draft.verified,
                comment:
                  draft.decision === "approved"
                    ? "Approved during the guided Catora client demo"
                    : "Rejected pending stronger source evidence",
              };
            }),
          }),
        },
      );
      setNotice("Review saved. The approved change set and projected intent outcome are ready.");
      await load();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Unable to save review decisions");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && !overview) {
    return <main className="shell demo-shell"><p className="loading-state">Preparing the client demo…</p></main>;
  }
  if (error && !overview) {
    return (
      <main className="shell demo-shell">
        <p className="form-error" role="alert">{error}</p>
        <button className="primary-button" onClick={() => void load()} type="button">Retry</button>
      </main>
    );
  }
  if (!overview) return null;

  return (
    <main className="shell demo-shell">
      <header className="demo-hero">
        <div>
          <p className="eyebrow">CLIENT-WINNING DEMO</p>
          <h1>{overview.workspace_name}</h1>
          <p className="lede">
            From catalog evidence to buyer-intent coverage, controlled decisions and an executive-ready proof package.
          </p>
        </div>
        <div className="demo-hero-actions">
          <Link className="secondary" href={`/workspace/${workspaceId}`}>Workspace home</Link>
          <a className="primary" href={absoluteApiPath(overview.report_pptx_path)}>Download executive PPTX</a>
        </div>
      </header>

      <nav className="demo-step-nav" aria-label="Demo steps">
        <a href="#overview">1. Overview</a>
        <a href="#findings">2. Defect</a>
        <a href="#intent">3. Buyer intent</a>
        <a href="#decision">4. Decision</a>
        <a href="#proof">5. Proof</a>
      </nav>

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="success-banner" role="status">{notice}</p> : null}

      <section className="demo-section" id="overview">
        <div className="section-heading">
          <div><p className="eyebrow">STEP 1</p><h2>Understand the catalog in seconds</h2></div>
          <span className="metric-confidence">{formatBasisPoints(overview.audit.confidence_basis_points)} source confidence</span>
        </div>
        <div className="metric-grid">
          <article className="metric-card metric-primary"><span>Catalog health</span><strong>{formatBasisPoints(overview.audit.score_basis_points)}</strong><small>Deterministic weighted score</small></article>
          <article className="metric-card"><span>Products analysed</span><strong>{overview.catalog.product_count}</strong><small>{overview.catalog.variant_count} variants</small></article>
          <article className="metric-card"><span>High-value findings</span><strong>{overview.audit.critical_count + overview.audit.high_count}</strong><small>Critical and high severity</small></article>
          <article className="metric-card"><span>Possible intent matches</span><strong>{overview.intent.possible_match_count}</strong><small>Relevant but missing evidence</small></article>
        </div>
        <div className="gap-grid">
          {overview.top_gaps.map((gap) => (
            <article className="gap-card" key={gap.field_key}>
              <strong>{gap.label}</strong><span>{gap.affected_products} products affected</span>
            </article>
          ))}
        </div>
      </section>

      <section className="demo-section" id="findings">
        <div className="section-heading">
          <div><p className="eyebrow">STEP 2</p><h2>Drill into a commercially meaningful defect</h2></div>
          <Link className="secondary" href={`/workspace/${workspaceId}/products/${overview.hero_product.id}`}>Open full product provenance</Link>
        </div>
        <article className="hero-product-card">
          <div>
            <span className="category-pill">{humanizeStatus(overview.hero_product.category_key)}</span>
            <h3>{overview.hero_product.title}</h3>
            <p>{overview.hero_product.canonical_key}</p>
          </div>
          <div className="evidence-stack">
            {overview.hero_product.source_evidence.slice(0, 3).map((item) => (
              <div className="evidence-card" key={`${item.field_path}-${item.source_label}`}>
                <strong>{item.field_path}</strong><span>{item.excerpt ?? "No source excerpt"}</span><small>{item.source_label}</small>
              </div>
            ))}
          </div>
        </article>
        <div className="finding-list">
          {overview.findings.slice(0, 5).map((finding) => (
            <article className="finding-card" key={finding.id}>
              <div><span className={severityClass(finding.severity)}>{finding.severity}</span><span className="impact-pill">{humanizeStatus(finding.business_impact)}</span></div>
              <h3>{finding.title}</h3><p>{finding.explanation}</p>
              <footer><span>{humanizeStatus(finding.field_key)}</span><span>{humanizeStatus(finding.remediation_type)}</span></footer>
            </article>
          ))}
        </div>
      </section>

      <section className="demo-section intent-section" id="intent">
        <div className="section-heading"><div><p className="eyebrow">STEP 3</p><h2>Connect data quality to a real buying question</h2></div></div>
        <blockquote>{overview.intent.query}</blockquote>
        <div className="intent-count-grid">
          <div><strong>{overview.intent.confident_match_count}</strong><span>Confident matches</span></div>
          <div><strong>{overview.intent.possible_match_count}</strong><span>Possible, missing data</span></div>
          <div><strong>{overview.intent.non_match_count}</strong><span>Non-matches</span></div>
        </div>
        <div className="before-after-grid">
          <article><span>Current persisted outcome</span><strong className="status-possible">{humanizeStatus(overview.intent.hero_product_before_status)}</strong><p>Missing: {overview.intent.missing_fields.join(", ")}</p></article>
          <article><span>After approved change</span><strong className="status-confident">{humanizeStatus(overview.intent.hero_product_after_status)}</strong><p>Projected only; nothing is published automatically.</p></article>
        </div>
      </section>

      <section className="demo-section" id="decision">
        <div className="section-heading"><div><p className="eyebrow">STEP 4</p><h2>Make a safe, attributable recommendation decision</h2></div><span className="status-pill">{humanizeStatus(overview.recommendation.status)}</span></div>
        <div className="recommendation-fields">
          {overview.recommendation.fields.map((field) => {
            const draft = drafts[field.id] ?? {
              decision: field.decision ?? undefined,
              editedValue: displayValue(field.edited_value ?? field.proposed_value),
              verified: !field.requires_verification,
            };
            return (
              <article className="recommendation-field" key={field.id}>
                <header><div><h3>{field.label}</h3><span>{field.confidence} confidence</span></div>{field.requires_verification ? <span className="verification-pill">Verification required</span> : <span className="clean-pill">Source supported</span>}</header>
                <div className="value-comparison"><div><span>Current</span><strong>{displayValue(field.original_value)}</strong></div><div><span>Proposed</span><input aria-label={`Edit ${field.label}`} onChange={(event) => updateDraft(field.id, { editedValue: event.target.value })} value={draft.editedValue} /></div></div>
                <div className="decision-row">
                  <button className={draft.decision === "approved" ? "decision-button selected" : "decision-button"} onClick={() => updateDraft(field.id, { decision: "approved" })} type="button">Approve</button>
                  <button className={draft.decision === "rejected" ? "decision-button selected danger" : "decision-button danger"} onClick={() => updateDraft(field.id, { decision: "rejected" })} type="button">Reject</button>
                  {field.requires_verification ? <label className="verify-check"><input checked={draft.verified} onChange={(event) => updateDraft(field.id, { verified: event.target.checked })} type="checkbox" />I verified this factual value</label> : null}
                </div>
                {field.decision ? <p className="persisted-decision">Previously recorded: {field.decision}{field.decision_comment ? ` — ${field.decision_comment}` : ""}</p> : null}
              </article>
            );
          })}
        </div>
        <button className="primary-button decision-submit" disabled={!allDecided || submitting} onClick={() => void submitDecisions()} type="button">{submitting ? "Saving decisions…" : "Create approved change set"}</button>
      </section>

      <section className="demo-section proof-section" id="proof">
        <div><p className="eyebrow">STEP 5</p><h2>Leave the client with forwardable proof</h2><p className="lede">The executive assessment and operational backlog are generated from the same persisted records shown above.</p></div>
        <div className="proof-actions">
          <a className="primary" href={absoluteApiPath(overview.report_pptx_path)}>Executive assessment PPTX</a>
          <a className="secondary" href={absoluteApiPath(overview.operational_csv_path)}>Operational backlog CSV</a>
        </div>
        <div className="pilot-roadmap"><h3>Recommended 90-day paid pilot</h3><ol><li>Ingest and baseline the client catalog.</li><li>Prioritize high-value evidence and buyer-intent gaps.</li><li>Approve controlled improvements without autonomous publishing.</li><li>Rerun coverage and deliver executive results.</li></ol></div>
      </section>
    </main>
  );
}
