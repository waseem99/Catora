"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import {
  createShopifyCsvSource,
  startCatalogIngestion,
  uploadShopifyCsv,
  validateCatalogSource,
} from "@/lib/onboarding";

type Props = { workspaceId: string };
type ResumeState = { sourceId?: string; jobId?: string };

function resumeKey(workspaceId: string, file: File): string {
  return `catora:csv-onboarding:${workspaceId}:${file.name}:${file.size}:${file.lastModified}`;
}

function readResume(key: string): ResumeState {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as ResumeState) : {};
  } catch {
    return {};
  }
}

function writeResume(key: string, value: ResumeState): void {
  window.sessionStorage.setItem(key, JSON.stringify(value));
}

export function CatalogOnboarding({ workspaceId }: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [sourceName, setSourceName] = useState("Shopify catalog diagnostic");
  const [status, setStatus] = useState("Choose a Shopify product CSV to begin.");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedFile = useMemo(() => {
    if (!file) return null;
    return `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  }, [file]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;

    setBusy(true);
    setError(null);
    const key = resumeKey(workspaceId, file);

    try {
      const resume = readResume(key);
      if (resume.jobId) {
        router.push(`/workspace/${workspaceId}/processing/${resume.jobId}`);
        return;
      }

      let sourceId = resume.sourceId;
      if (!sourceId) {
        setStatus("Uploading the CSV securely…");
        const upload = await uploadShopifyCsv(workspaceId, file);
        setStatus("Creating a tenant-scoped catalog source…");
        const source = await createShopifyCsvSource(
          workspaceId,
          upload.object_key,
          sourceName.trim() || "Shopify catalog diagnostic",
        );
        sourceId = source.id;
        writeResume(key, { sourceId });
      }

      setStatus("Validating Shopify headers and mappings…");
      const validation = await validateCatalogSource(workspaceId, sourceId);
      if (!validation.valid) {
        throw new Error(validation.errors.join(" ") || "The CSV could not be validated.");
      }

      setStatus("Queueing product import and normalization…");
      const job = await startCatalogIngestion(workspaceId, sourceId);
      writeResume(key, { sourceId, jobId: job.id });
      router.push(`/workspace/${workspaceId}/processing/${job.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start the diagnostic.");
      setStatus("Your progress is saved. Correct the issue and retry.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell onboarding-shell">
      <header className="onboarding-header">
        <div>
          <p className="eyebrow">CHOOSE YOUR STARTING POINT</p>
          <h1>Bring a catalog into Catora</h1>
          <p className="lede">
            Explore the prepared enterprise story, run a one-time Shopify CSV diagnostic, or prepare
            a continuous Shopify pilot.
          </p>
        </div>
        <Link className="secondary onboarding-back" href={`/workspace/${workspaceId}`}>
          Back to workspace
        </Link>
      </header>

      <section className="onboarding-paths" aria-label="Catalog onboarding paths">
        <article className="onboarding-card featured-card">
          <span className="path-number">01</span>
          <p className="eyebrow">NO SETUP · 2 MINUTES</p>
          <h2>Explore sample catalog</h2>
          <p>
            Open the deterministic Northstar demonstration with 1,000 products, 2,000 SKUs,
            evidence-backed defects and a complete recommendation story.
          </p>
          <ul>
            <li>No merchant permissions required</li>
            <li>Safe reset before every presentation</li>
            <li>Executive PPTX and operational CSV included</li>
          </ul>
          <Link className="primary path-action" href={`/workspace/${workspaceId}/demo`}>
            Launch sample experience
          </Link>
        </article>

        <article className="onboarding-card">
          <span className="path-number">02</span>
          <p className="eyebrow">ONE-TIME DIAGNOSTIC</p>
          <h2>Upload Shopify CSV</h2>
          <p>
            Use Shopify’s product export format. Catora validates headers, imports variants and
            preserves inherited product fields across Shopify’s multi-row products.
          </p>
          <form className="csv-onboarding-form" onSubmit={submit}>
            <label>
              Diagnostic name
              <input
                value={sourceName}
                onChange={(event) => setSourceName(event.target.value)}
                maxLength={200}
                required
              />
            </label>
            <label className="file-field">
              Shopify product CSV
              <input
                type="file"
                accept=".csv,text/csv,application/csv,application/vnd.ms-excel"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                required
              />
              <span>{selectedFile ?? "Select the CSV exported from Shopify Products"}</span>
            </label>
            <button className="primary-button path-action" disabled={!file || busy} type="submit">
              {busy ? "Starting diagnostic…" : "Upload and analyze"}
            </button>
            <p className="form-status" aria-live="polite">{status}</p>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
          </form>
        </article>

        <article className="onboarding-card pilot-card">
          <span className="path-number">03</span>
          <p className="eyebrow">CONTINUOUS PAID PILOT</p>
          <h2>Connect Shopify</h2>
          <p>
            A private custom-app installation will keep products synchronized and process merchant
            webhooks without requiring a public App Store listing.
          </p>
          <ul>
            <li>Read-only catalog access first</li>
            <li>Encrypted credential lifecycle</li>
            <li>Explicit uninstall and data-retention controls</li>
          </ul>
          <button className="secondary-button path-action" type="button" disabled>
            Available after pilot app registration
          </button>
          <small>
            Your operator will enable this path after the Shopify development store and private app
            are registered.
          </small>
        </article>
      </section>
    </main>
  );
}
