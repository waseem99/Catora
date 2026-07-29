"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createServiceVisibilitySource,
  listServiceVisibilityRuns,
  listServiceVisibilitySources,
  runServiceVisibility,
  serviceVisibilityArtifactUrl,
  type ServiceVisibilityProvision,
  type ServiceVisibilityRun,
  type ServiceVisibilitySource,
} from "@/lib/service-visibility";

type Props = { workspaceId: string };

const artifactLabels: Record<string, string> = {
  service_visibility_json: "Evidence JSON",
  service_visibility_findings_csv: "Findings CSV",
  service_visibility_questions_csv: "Buyer questions CSV",
  service_visibility_content_brief: "Content brief",
  service_visibility_pptx: "Executive presentation",
};

export function ServiceVisibilityConsole({ workspaceId }: Props) {
  const [sources, setSources] = useState<ServiceVisibilitySource[]>([]);
  const [runs, setRuns] = useState<ServiceVisibilityRun[]>([]);
  const [name, setName] = useState("");
  const [siteUrl, setSiteUrl] = useState("");
  const [mode, setMode] = useState<"zero_install" | "wordpress_bridge">("zero_install");
  const [monitoring, setMonitoring] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [provision, setProvision] = useState<ServiceVisibilityProvision | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [nextSources, nextRuns] = await Promise.all([
      listServiceVisibilitySources(workspaceId),
      listServiceVisibilityRuns(workspaceId),
    ]);
    setSources(nextSources);
    setRuns(nextRuns);
  }, [workspaceId]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      listServiceVisibilitySources(workspaceId),
      listServiceVisibilityRuns(workspaceId),
    ]).then(([nextSources, nextRuns]) => {
      if (cancelled) return;
      setSources(nextSources);
      setRuns(nextRuns);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (!runs.some((run) => ["queued", "running"].includes(run.status))) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh, runs]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authorized || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createServiceVisibilitySource(workspaceId, {
        name: name.trim(),
        site_url: siteUrl.trim(),
        connection_mode: mode,
        authorized_domain_confirmed: true,
        monitoring_enabled: monitoring,
      });
      setProvision(created);
      setName("");
      setSiteUrl("");
      setAuthorized(false);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create the source.");
    } finally {
      setBusy(false);
    }
  }

  async function run(sourceId: string) {
    setBusy(true);
    setError(null);
    try {
      await runServiceVisibility(workspaceId, sourceId);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start the audit.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell service-visibility-shell">
      <header className="service-visibility-header">
        <div>
          <p className="eyebrow">WORDPRESS SERVICE VISIBILITY</p>
          <h1>Audit services for search and answer readiness</h1>
          <p className="lede">
            Analyze authorized public WordPress pages, trace every finding to page evidence,
            and prepare human-approved fixes without promising rankings or AI citations.
          </p>
        </div>
        <Link className="secondary" href={`/workspace/${workspaceId}`}>Back to workspace</Link>
      </header>

      {error ? <p className="service-error">{error}</p> : null}

      <section className="service-grid">
        <article className="service-panel">
          <h2>Add a service website</h2>
          <form className="service-form" onSubmit={create}>
            <label>Source name<input required minLength={2} value={name} onChange={(event) => setName(event.target.value)} placeholder="Codistan service website" /></label>
            <label>HTTPS website URL<input required type="url" value={siteUrl} onChange={(event) => setSiteUrl(event.target.value)} placeholder="https://example.com" /></label>
            <label>Connection mode<select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}><option value="zero_install">Zero-install public audit</option><option value="wordpress_bridge">WordPress bridge</option></select></label>
            <label className="service-check"><input type="checkbox" checked={monitoring} onChange={(event) => setMonitoring(event.target.checked)} /> Enable recurring monitoring after deployment approval</label>
            <label className="service-check"><input required type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} /> I confirm authorization to audit this public domain.</label>
            <button className="primary-button" disabled={!authorized || busy} type="submit">{busy ? "Working…" : "Create source"}</button>
          </form>
          {provision?.connection_mode === "wordpress_bridge" ? (
            <div className="service-secret">
              <strong>Copy the bridge credentials now</strong>
              <code>{provision.endpoint}</code>
              <code>{provision.id}</code>
              <code>{provision.token}</code>
              <small>The token is shown only in this response. Deliver it through an approved secret channel.</small>
            </div>
          ) : null}
        </article>

        <article className="service-panel">
          <h2>Configured sources</h2>
          <div className="service-list">
            {sources.length === 0 ? <p>No WordPress service sources yet.</p> : sources.map((source) => (
              <div className="service-source" key={source.id}>
                <div><strong>{source.name}</strong><span>{source.site_url}</span><small>{source.connection_mode.replaceAll("_", " ")} · {source.status}</small></div>
                <button disabled={busy || source.connection_mode === "wordpress_bridge" && source.status === "draft"} onClick={() => void run(source.id)} type="button">Run audit</button>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="service-panel">
        <h2>Audit runs</h2>
        <div className="service-runs">
          {runs.length === 0 ? <p>No audits have been started.</p> : runs.map((runItem) => (
            <article key={runItem.id}>
              <header><strong>{runItem.status}</strong><span>{new Date(runItem.created_at).toLocaleString()}</span></header>
              <div className="service-metrics"><span>Pages <b>{runItem.page_count}</b></span><span>Findings <b>{runItem.finding_count}</b></span><span>Questions <b>{runItem.question_count}</b></span><span>Score <b>{runItem.scorecard.overall ?? "—"}</b></span></div>
              {runItem.error ? <p>{runItem.error}</p> : null}
              <div className="service-artifacts">
                {runItem.artifacts.map((artifact) => (
                  <a href={serviceVisibilityArtifactUrl(workspaceId, runItem.id, artifact)} key={artifact}>{artifactLabels[artifact] ?? artifact}</a>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
