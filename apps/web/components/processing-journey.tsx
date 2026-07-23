"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  IngestionJob,
  listIngestionJobs,
  normalizationSummary,
} from "@/lib/onboarding";

type Props = { workspaceId: string; jobId: string };
type StageState = "pending" | "active" | "completed" | "warning" | "failed" | "cancelled";
type Stage = { key: string; label: string; state: StageState; detail: string };

function terminalState(job: IngestionJob): StageState {
  if (job.status === "failed") return "failed";
  if (job.status === "cancelled") return "cancelled";
  if (job.status === "partially_completed" || job.rejection_count > 0 || job.warning_count > 0) {
    return "warning";
  }
  return "completed";
}

function stagesFor(job: IngestionJob): Stage[] {
  const normalization = normalizationSummary(job);
  const terminal = ["completed", "partially_completed", "failed", "cancelled"].includes(job.status);
  const importState: StageState = terminal
    ? terminalState(job)
    : job.status === "queued"
      ? "pending"
      : "active";
  const normalizationState: StageState = normalization
    ? terminalState(job)
    : job.status === "failed"
      ? "failed"
      : job.status === "cancelled"
        ? "cancelled"
        : job.status === "completed" || job.status === "partially_completed"
          ? "active"
          : "pending";

  return [
    {
      key: "upload",
      label: "Uploading catalog",
      state: "completed",
      detail: "The CSV is stored privately inside this workspace.",
    },
    {
      key: "validation",
      label: "Validating Shopify source",
      state: "completed",
      detail: "Required Shopify headers and the explicit field mapping were validated.",
    },
    {
      key: "import",
      label: "Retrieving and importing products",
      state: importState,
      detail: `${job.processed_count.toLocaleString()} rows processed · ${job.success_count.toLocaleString()} accepted · ${job.rejection_count.toLocaleString()} rejected`,
    },
    {
      key: "normalization",
      label: "Normalizing products and variants",
      state: normalizationState,
      detail: normalization
        ? "Canonical products, variants and evidence were persisted from the source rows."
        : "Waiting for the persisted normalization summary from the worker.",
    },
    {
      key: "taxonomy",
      label: "Assigning taxonomy",
      state: normalizationState,
      detail: normalization
        ? "Product categories and normalized attributes are ready for review."
        : "Taxonomy is assigned only as part of completed normalization.",
    },
    {
      key: "audit",
      label: "Running deterministic audits",
      state: "pending",
      detail: "The prospect-specific audit orchestration is the next assessment stage; no completion is claimed yet.",
    },
    {
      key: "intent",
      label: "Testing buyer intents",
      state: "pending",
      detail: "Buyer-intent testing begins only after a persisted audit snapshot is available.",
    },
    {
      key: "reports",
      label: "Preparing recommendations and reports",
      state: "pending",
      detail: "Recommendations and client-branded reports require completed persisted analysis.",
    },
  ];
}

export function ProcessingJourney({ workspaceId, jobId }: Props) {
  const router = useRouter();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(true);

  const load = useCallback(async () => {
    try {
      const jobs = await listIngestionJobs(workspaceId);
      const current = jobs.find((candidate) => candidate.id === jobId);
      if (!current) throw new Error("The catalog processing job was not found in this workspace.");
      setJob(current);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to refresh processing status.");
    } finally {
      setRefreshing(false);
    }
  }, [jobId, workspaceId]);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 1800);
    return () => window.clearInterval(interval);
  }, [load]);

  const stages = useMemo(() => (job ? stagesFor(job) : []), [job]);
  const normalized = job ? normalizationSummary(job) !== null : false;
  const importComplete = job
    ? ["completed", "partially_completed"].includes(job.status) && normalized
    : false;

  useEffect(() => {
    if (!importComplete) return;
    const timeout = window.setTimeout(() => {
      router.replace(`/workspace/${workspaceId}/products`);
    }, 3500);
    return () => window.clearTimeout(timeout);
  }, [importComplete, router, workspaceId]);

  return (
    <main className="shell onboarding-shell processing-shell">
      <header className="onboarding-header">
        <div>
          <p className="eyebrow">CATALOG PROCESSING</p>
          <h1>{importComplete ? "Your catalog is ready" : "Catora is preparing your catalog"}</h1>
          <p className="lede">
            Every completed stage below is backed by persisted job state. Catora does not invent a
            percentage when the remaining work does not have a defensible denominator.
          </p>
        </div>
        <Link className="secondary onboarding-back" href={`/workspace/${workspaceId}/onboarding`}>
          Onboarding choices
        </Link>
      </header>

      {error ? (
        <section className="processing-alert warning-alert" role="alert">
          <strong>Live refresh unavailable</strong>
          <p>{error}</p>
          {job ? <small>The last verified persisted status remains visible below.</small> : null}
          <button className="secondary-button" type="button" onClick={() => void load()}>
            Retry status
          </button>
        </section>
      ) : null}

      {job ? (
        <>
          <section className="processing-summary" aria-label="Import counts">
            <div><span>Job state</span><strong>{job.status.replaceAll("_", " ")}</strong></div>
            <div><span>Rows processed</span><strong>{job.processed_count.toLocaleString()}</strong></div>
            <div><span>Rows accepted</span><strong>{job.success_count.toLocaleString()}</strong></div>
            <div><span>Warnings</span><strong>{job.warning_count.toLocaleString()}</strong></div>
          </section>

          <section className="processing-timeline" aria-label="Catalog processing stages">
            {stages.map((stage, index) => (
              <article className={`processing-stage stage-${stage.state}`} key={stage.key}>
                <div className="stage-marker" aria-hidden="true">{index + 1}</div>
                <div>
                  <header>
                    <h2>{stage.label}</h2>
                    <span>{stage.state}</span>
                  </header>
                  <p>{stage.detail}</p>
                </div>
              </article>
            ))}
          </section>

          {importComplete ? (
            <section className="processing-alert success-alert">
              <strong>Import and normalization completed</strong>
              <p>
                Opening the persisted product catalog automatically. The deterministic audit,
                buyer-intent and branded-report stages remain clearly marked as not started.
              </p>
              <Link className="primary path-action" href={`/workspace/${workspaceId}/products`}>
                Open catalog now
              </Link>
            </section>
          ) : null}

          {job.status === "failed" || job.status === "cancelled" ? (
            <section className="processing-alert danger-alert">
              <strong>Processing stopped</strong>
              <p>
                Return to onboarding to retry the same locally remembered source, or choose another
                catalog path. No raw source rows are shown in this status screen.
              </p>
              <Link className="secondary path-action" href={`/workspace/${workspaceId}/onboarding`}>
                Return to onboarding
              </Link>
            </section>
          ) : null}
        </>
      ) : (
        <p className="loading-state">{refreshing ? "Loading persisted processing state…" : "No status is available."}</p>
      )}
    </main>
  );
}
