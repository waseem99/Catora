"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import { createDiagnostic, uploadDiagnosticCsv } from "@/lib/diagnostics";

type Props = { workspaceId: string };
type ResumeState = { assessmentId?: string; diagnosticWorkspaceId?: string };

function resumeKey(workspaceId: string, file: File, companyName: string): string {
  const company = companyName.trim().toLowerCase().replaceAll(/\s+/g, "-");
  return `catora:prospect-diagnostic:${workspaceId}:${company}:${file.name}:${file.size}:${file.lastModified}`;
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
  const [companyName, setCompanyName] = useState("");
  const [marketCode, setMarketCode] = useState("AE");
  const [locale, setLocale] = useState("en-AE");
  const [currency, setCurrency] = useState("AED");
  const [storefrontDomain, setStorefrontDomain] = useState("");
  const [retentionDays, setRetentionDays] = useState("30");
  const [authorized, setAuthorized] = useState(false);
  const [status, setStatus] = useState(
    "Enter the prospect details and choose their Shopify product export.",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedFile = useMemo(() => {
    if (!file) return null;
    return `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  }, [file]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy || !authorized) return;

    setBusy(true);
    setError(null);
    const key = resumeKey(workspaceId, file, companyName);

    try {
      const resume = readResume(key);
      let assessmentId = resume.assessmentId;
      let diagnosticWorkspaceId = resume.diagnosticWorkspaceId;

      if (!assessmentId || !diagnosticWorkspaceId) {
        setStatus("Creating an isolated prospect workspace…");
        const diagnostic = await createDiagnostic(workspaceId, {
          company_name: companyName.trim(),
          market_code: marketCode.trim().toUpperCase(),
          locale: locale.trim(),
          currency: currency.trim().toUpperCase(),
          retention_days: Number.parseInt(retentionDays, 10),
          authorization_confirmed: authorized,
          ...(storefrontDomain.trim()
            ? { storefront_domain: storefrontDomain.trim() }
            : {}),
        });
        assessmentId = diagnostic.id;
        diagnosticWorkspaceId = diagnostic.workspace_id;
        writeResume(key, { assessmentId, diagnosticWorkspaceId });
      }

      setStatus("Uploading and validating the Shopify export…");
      await uploadDiagnosticCsv(assessmentId, file);
      setStatus("The automated assessment is running…");
      router.push(
        `/workspace/${diagnosticWorkspaceId}/diagnostic/${assessmentId}`,
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Unable to start the prospect assessment.",
      );
      setStatus(
        "Your assessment identifiers are saved. Correct the source issue and retry.",
      );
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = Boolean(
    file && companyName.trim().length >= 2 && authorized && !busy,
  );

  return (
    <main className="shell onboarding-shell">
      <header className="onboarding-header">
        <div>
          <p className="eyebrow">CHOOSE YOUR STARTING POINT</p>
          <h1>Bring a catalog into Catora</h1>
          <p className="lede">
            Explore the prepared enterprise story, run a prospect-specific Shopify CSV
            assessment, or prepare a continuous Shopify pilot.
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
            Open the deterministic Northstar demonstration with 1,000 products, 2,000
            SKUs, evidence-backed defects and a complete recommendation story.
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

        <article className="onboarding-card diagnostic-intake-card">
          <span className="path-number">02</span>
          <p className="eyebrow">PROSPECT-SPECIFIC DIAGNOSTIC</p>
          <h2>Upload Shopify CSV</h2>
          <p>
            Create an isolated, branded workspace and automatically run ingestion,
            normalization, taxonomy, audit, buyer-intent testing and reporting.
          </p>
          <form className="csv-onboarding-form" onSubmit={submit}>
            <label>
              Prospect company
              <input
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                placeholder="Lama Furniture"
                maxLength={200}
                required
              />
            </label>
            <div className="diagnostic-form-grid">
              <label>
                Market
                <input
                  value={marketCode}
                  onChange={(event) => setMarketCode(event.target.value)}
                  maxLength={35}
                  required
                />
              </label>
              <label>
                Locale
                <input
                  value={locale}
                  onChange={(event) => setLocale(event.target.value)}
                  maxLength={35}
                  required
                />
              </label>
              <label>
                Currency
                <input
                  value={currency}
                  onChange={(event) => setCurrency(event.target.value)}
                  maxLength={3}
                  required
                />
              </label>
              <label>
                Retention days
                <input
                  type="number"
                  value={retentionDays}
                  onChange={(event) => setRetentionDays(event.target.value)}
                  min={1}
                  max={90}
                  required
                />
              </label>
            </div>
            <label>
              Shopify domain <span className="optional-label">optional</span>
              <input
                value={storefrontDomain}
                onChange={(event) => setStorefrontDomain(event.target.value)}
                placeholder="store.myshopify.com"
                maxLength={255}
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
              <span>{selectedFile ?? "Select Shopify’s all-products export"}</span>
            </label>
            <label className="authorization-field">
              <input
                type="checkbox"
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
                required
              />
              <span>
                I confirm the prospect has authorized this catalog diagnostic and the
                selected retention window.
              </span>
            </label>
            <button className="primary-button path-action" disabled={!canSubmit} type="submit">
              {busy ? "Starting assessment…" : "Upload and run full assessment"}
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
            A private custom-app installation will keep products synchronized and process
            merchant webhooks without requiring a public App Store listing.
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
            Your operator will enable this path after the Shopify development store and
            private app are registered.
          </small>
        </article>
      </section>
    </main>
  );
}
