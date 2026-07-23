"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  DIAGNOSTIC_STAGES,
  Diagnostic,
  DiagnosticRejectionList,
  deleteDiagnostic,
  diagnosticDownloadUrl,
  diagnosticStageState,
  getDiagnostic,
  getDiagnosticRejections,
} from "@/lib/diagnostics";

type Props = {
  workspaceId: string;
  assessmentId: string;
};

function number(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function date(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ProspectDiagnostic({ workspaceId, assessmentId }: Props) {
  const router = useRouter();
  const [diagnostic, setDiagnostic] = useState<Diagnostic | null>(null);
  const [lastVerified, setLastVerified] = useState<Diagnostic | null>(null);
  const [rejections, setRejections] = useState<DiagnosticRejectionList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      try {
        const next = await getDiagnostic(assessmentId);
        if (!active) return;
        setDiagnostic(next);
        setLastVerified(next);
        setError(null);
        if (next.counts.rejected_rows > 0 && !rejections) {
          const rejected = await getDiagnosticRejections(assessmentId);
          if (active) setRejections(rejected);
        }
        if (!["completed", "failed", "deleting"].includes(next.status)) {
          timer = setTimeout(refresh, 1800);
        }
      } catch (caught) {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to refresh the assessment.");
        timer = setTimeout(refresh, 3500);
      }
    }

    void refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [assessmentId, rejections]);

  const view = diagnostic ?? lastVerified;
  const downloadable = view?.status === "completed";
  const verifiedLabel = useMemo(
    () => (lastVerified ? date(lastVerified.updated_at) : null),
    [lastVerified],
  );

  async function removeAssessment() {
    if (!view || deleting) return;
    const confirmed = window.confirm(
      `Delete the ${view.company_name} diagnostic workspace and its uploaded catalog?`,
    );
    if (!confirmed) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteDiagnostic(assessmentId);
      router.push("/workspaces");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete the assessment.");
      setDeleting(false);
    }
  }

  if (!view) {
    return (
      <main className="shell diagnostic-shell">
        <p className="eyebrow">PROSPECT DIAGNOSTIC</p>
        <h1>Preparing the assessment…</h1>
        <p className="lede">Catora is loading the persisted diagnostic state.</p>
        {error ? <p className="form-error">{error}</p> : null}
      </main>
    );
  }

  return (
    <main className="shell diagnostic-shell">
      <header className="diagnostic-header">
        <div>
          <p className="eyebrow">PROSPECT-SPECIFIC CATALOG ASSESSMENT</p>
          <h1>{view.company_name}</h1>
          <p className="lede">
            {view.market_code} · {view.locale} · {view.currency}. Every count below is reconciled to
            persisted Catora records.
          </p>
        </div>
        <div className="diagnostic-header-actions">
          <Link className="secondary" href={`/workspace/${workspaceId}/products`}>
            Browse imported catalog
          </Link>
          <button
            className="danger-button"
            type="button"
            disabled={deleting}
            onClick={removeAssessment}
          >
            {deleting ? "Deleting…" : "Delete diagnostic"}
          </button>
        </div>
      </header>

      <section className={`diagnostic-status diagnostic-status-${view.status}`}>
        <div>
          <span>Current stage</span>
          <strong>{view.current_stage}</strong>
          <p>{view.detail}</p>
        </div>
        <div>
          <span>Retention deadline</span>
          <strong>{date(view.retention_expires_at)}</strong>
          <p>The uploaded catalog can be removed earlier using the protected delete action.</p>
        </div>
      </section>

      {error ? (
        <section className="diagnostic-notice warning-alert">
          <strong>Live refresh is temporarily unavailable</strong>
          <p>
            {error} {verifiedLabel ? `Showing the last verified state from ${verifiedLabel}.` : ""}
          </p>
        </section>
      ) : null}

      {view.status === "failed" ? (
        <section className="diagnostic-notice danger-alert">
          <strong>{view.failure_code ?? "Assessment stopped safely"}</strong>
          <p>{view.failure_detail ?? "Review the source file and retry from onboarding."}</p>
        </section>
      ) : null}

      <section className="diagnostic-metrics" aria-label="Diagnostic counts">
        <article><span>Rows processed</span><strong>{number(view.counts.processed_rows)}</strong></article>
        <article><span>Products</span><strong>{number(view.counts.product_count)}</strong></article>
        <article><span>Variants / SKUs</span><strong>{number(view.counts.variant_count)}</strong></article>
        <article><span>Evidence-backed findings</span><strong>{number(view.counts.finding_count)}</strong></article>
        <article><span>Buyer intents tested</span><strong>{number(view.counts.intent_run_count)}</strong></article>
        <article><span>Intent matches evaluated</span><strong>{number(view.counts.intent_match_count)}</strong></article>
      </section>

      <section className="diagnostic-layout">
        <div className="diagnostic-timeline">
          <header>
            <p className="eyebrow">AUTOMATED JOURNEY</p>
            <h2>From Shopify export to executive proof</h2>
          </header>
          {DIAGNOSTIC_STAGES.map((stage, index) => {
            const state = diagnosticStageState(view.status, stage.status);
            return (
              <article className={`diagnostic-stage stage-${state}`} key={stage.status}>
                <span className="stage-marker">{state === "completed" ? "✓" : index + 1}</span>
                <div>
                  <strong>{stage.label}</strong>
                  <span>{state}</span>
                </div>
              </article>
            );
          })}
        </div>

        <aside className="diagnostic-evidence-panel">
          <p className="eyebrow">DATA QUALITY CONTROLS</p>
          <h2>Nothing silently disappears</h2>
          <dl>
            <div><dt>Accepted rows</dt><dd>{number(view.counts.accepted_rows)}</dd></div>
            <div><dt>Rejected rows</dt><dd>{number(view.counts.rejected_rows)}</dd></div>
            <div><dt>Import warnings</dt><dd>{number(view.counts.warning_count)}</dd></div>
            <div><dt>Taxonomy assigned</dt><dd>{number(view.counts.assigned_category_count)}</dd></div>
            <div><dt>Ambiguous categories</dt><dd>{number(view.counts.ambiguous_category_count)}</dd></div>
            <div><dt>Unclassified</dt><dd>{number(view.counts.unclassified_category_count)}</dd></div>
          </dl>
        </aside>
      </section>

      {rejections?.items.length ? (
        <section className="diagnostic-rejections">
          <header>
            <div>
              <p className="eyebrow">BOUNDED REJECTION REPORT</p>
              <h2>Rows requiring attention</h2>
            </div>
            <span>
              Showing {rejections.items.length} of {number(rejections.total_rejected)} rejected rows
            </span>
          </header>
          <div className="rejection-list">
            {rejections.items.map((item) => (
              <article key={`${item.row_number}:${item.reason}`}>
                <strong>Row {item.row_number}</strong>
                <span>{item.reason}</span>
                <small>
                  {[item.product_handle, item.variant_sku].filter(Boolean).join(" · ") ||
                    "No safe product identifier available"}
                </small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className={`diagnostic-deliverables ${downloadable ? "deliverables-ready" : ""}`}>
        <div>
          <p className="eyebrow">CLIENT-READY OUTPUTS</p>
          <h2>{downloadable ? "The assessment is ready" : "Deliverables unlock at completion"}</h2>
          <p>
            The executive deck and operational backlog are generated from the same findings and
            buyer-intent results displayed here.
          </p>
        </div>
        <div className="diagnostic-downloads">
          {downloadable ? (
            <>
              <a className="primary path-action" href={diagnosticDownloadUrl(view.report_path)}>
                Download executive PPTX
              </a>
              <a className="secondary path-action" href={diagnosticDownloadUrl(view.backlog_path)}>
                Download operational CSV
              </a>
            </>
          ) : (
            <span className="warning-pill">Processing persisted records</span>
          )}
        </div>
      </section>
    </main>
  );
}
