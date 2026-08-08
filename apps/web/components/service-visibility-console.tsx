"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  approveServiceVisibilityDraft,
  createServiceVisibilityDraft,
  createServiceVisibilitySource,
  getServiceVisibilityReport,
  listServiceVisibilityRuns,
  listServiceVisibilitySources,
  rotateServiceVisibilitySource,
  runServiceVisibility,
  serviceVisibilityArtifactUrl,
  type ServiceVisibilityDraft,
  type ServiceVisibilityFinding,
  type ServiceVisibilityProvision,
  type ServiceVisibilityReport,
  type ServiceVisibilityRun,
  type ServiceVisibilitySource,
} from "@/lib/service-visibility";

type Props = { workspaceId: string };

type DraftEditor = {
  finding: ServiceVisibilityFinding;
  pageUrl: string;
  wordpressPostId: number;
  baseRevision: string;
  title: string;
  metaTitle: string;
  metaDescription: string;
  content: string;
};

const artifactLabels: Record<string, string> = {
  service_visibility_json: "Evidence JSON",
  service_visibility_findings_csv: "Findings CSV",
  service_visibility_questions_csv: "Buyer questions CSV",
  service_visibility_content_brief: "Content brief",
  service_visibility_pptx: "Executive presentation",
};

const severityRank: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  informational: 4,
};

function conciseDescription(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (compact.length <= 155) return compact;
  const shortened = compact.slice(0, 155);
  const boundary = shortened.lastIndexOf(" ");
  return `${shortened.slice(0, boundary > 100 ? boundary : 152).trim()}…`;
}

function continuityLength(run: ServiceVisibilityRun, key: string): number {
  const value = run.continuity[key];
  return Array.isArray(value) ? value.length : 0;
}

export function ServiceVisibilityConsole({ workspaceId }: Props) {
  const [sources, setSources] = useState<ServiceVisibilitySource[]>([]);
  const [runs, setRuns] = useState<ServiceVisibilityRun[]>([]);
  const [name, setName] = useState("");
  const [siteUrl, setSiteUrl] = useState("");
  const [mode, setMode] = useState<"zero_install" | "wordpress_bridge">("zero_install");
  const [monitoring, setMonitoring] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [provision, setProvision] = useState<ServiceVisibilityProvision | null>(null);
  const [reviewRunId, setReviewRunId] = useState<string | null>(null);
  const [report, setReport] = useState<ServiceVisibilityReport | null>(null);
  const [editor, setEditor] = useState<DraftEditor | null>(null);
  const [draft, setDraft] = useState<ServiceVisibilityDraft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
    if (!runs.some((runItem) => ["queued", "running"].includes(runItem.status))) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh, runs]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authorized || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
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

  async function rotate(source: ServiceVisibilitySource) {
    if (busy) return;
    const confirmed = window.confirm(
      `Rotate the WordPress bridge credential for ${source.name}? The current credential will stop working immediately.`,
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const rotated = await rotateServiceVisibilitySource(workspaceId, source.id);
      setProvision(rotated);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to rotate the bridge credential.");
    } finally {
      setBusy(false);
    }
  }

  async function run(sourceId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await runServiceVisibility(workspaceId, sourceId);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start the audit.");
    } finally {
      setBusy(false);
    }
  }

  async function reviewFixes(runItem: ServiceVisibilityRun) {
    setBusy(true);
    setError(null);
    setNotice(null);
    setEditor(null);
    setDraft(null);
    try {
      const nextReport = await getServiceVisibilityReport(workspaceId, runItem.id);
      setReport(nextReport);
      setReviewRunId(runItem.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load report evidence.");
    } finally {
      setBusy(false);
    }
  }

  function prepareDraft(finding: ServiceVisibilityFinding) {
    if (!report || !finding.page_url) return;
    const page = report.site.pages.find((item) => item.url === finding.page_url);
    const postId = page?.wordpress.post_id;
    const revision = page?.wordpress.revision;
    if (!page || typeof postId !== "number" || typeof revision !== "string") {
      setError("This finding is not backed by a WordPress page revision, so it cannot be sent as a draft.");
      return;
    }
    const h1 = page.headings.find((heading) => heading.level === "h1")?.text ?? "";
    const titleSuggestion = finding.code.includes("title") ? (h1 || page.title).slice(0, 65) : "";
    const descriptionSuggestion = finding.code === "seo.missing_description"
      ? conciseDescription(page.visible_text)
      : "";
    setEditor({
      finding,
      pageUrl: page.url,
      wordpressPostId: postId,
      baseRevision: revision,
      title: "",
      metaTitle: titleSuggestion,
      metaDescription: descriptionSuggestion,
      content: "",
    });
    setDraft(null);
    setNotice(null);
    setError(null);
  }

  async function saveDraftProposal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor || !reviewRunId || busy) return;
    const proposed = {
      ...(editor.title.trim() ? { title: editor.title.trim() } : {}),
      ...(editor.content.trim() ? { content: editor.content.trim() } : {}),
      ...(editor.metaTitle.trim() ? { meta_title: editor.metaTitle.trim() } : {}),
      ...(editor.metaDescription.trim() ? { meta_description: editor.metaDescription.trim() } : {}),
    };
    if (Object.keys(proposed).length === 0) {
      setError("Enter at least one proposed change before creating the WordPress draft proposal.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createServiceVisibilityDraft(workspaceId, reviewRunId, {
        page_url: editor.pageUrl,
        wordpress_post_id: editor.wordpressPostId,
        base_revision: editor.baseRevision,
        ...proposed,
      });
      setDraft(created);
      setNotice("Proposal prepared. Review it once more, then approve it for WordPress delivery.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to prepare the WordPress draft proposal.");
    } finally {
      setBusy(false);
    }
  }

  async function approveDraft() {
    if (!draft || busy) return;
    const confirmed = window.confirm(
      "Approve this proposal for WordPress draft delivery? It will remain unpublished and will not overwrite the live page.",
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const approved = await approveServiceVisibilityDraft(workspaceId, draft.source_id, draft.id);
      setDraft(approved);
      setNotice(
        "Approved for WordPress. With Approved Drafts enabled on the plugin, WordPress will collect this proposal on the next monitored snapshot and create an unpublished draft copy.",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to approve the WordPress draft proposal.");
    } finally {
      setBusy(false);
    }
  }

  const findings = report
    ? [...report.findings].sort((left, right) => (
      (severityRank[left.severity] ?? 99) - (severityRank[right.severity] ?? 99)
    ))
    : [];

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
      {notice ? <p className="service-notice">{notice}</p> : null}

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
                <nav className="service-source-actions" aria-label={`${source.name} actions`}>
                  {source.connection_mode === "wordpress_bridge" ? (
                    <button disabled={busy} onClick={() => void rotate(source)} type="button">Rotate credential</button>
                  ) : null}
                  <button disabled={busy || source.connection_mode === "wordpress_bridge" && source.status === "draft"} onClick={() => void run(source.id)} type="button">Run audit</button>
                </nav>
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
              {runItem.status === "completed" ? (
                <div className="service-change-summary">
                  <span>New pages <b>{continuityLength(runItem, "new_pages")}</b></span>
                  <span>Changed <b>{continuityLength(runItem, "changed_pages")}</b></span>
                  <span>Removed <b>{continuityLength(runItem, "removed_pages")}</b></span>
                </div>
              ) : null}
              {runItem.error ? <p>{runItem.error}</p> : null}
              <div className="service-artifacts">
                {runItem.artifacts.map((artifact) => (
                  <a href={serviceVisibilityArtifactUrl(workspaceId, runItem.id, artifact)} key={artifact}>{artifactLabels[artifact] ?? artifact}</a>
                ))}
                {runItem.status === "completed" && runItem.artifacts.includes("report_json") ? (
                  <button disabled={busy} onClick={() => void reviewFixes(runItem)} type="button">Review fixes</button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      {report && reviewRunId ? (
        <section className="service-panel service-fix-review">
          <header className="service-fix-header">
            <div><p className="eyebrow">HUMAN-APPROVED REMEDIATION</p><h2>Review fixes for {report.site.company_name}</h2></div>
            <button onClick={() => { setReport(null); setReviewRunId(null); setEditor(null); setDraft(null); }} type="button">Close</button>
          </header>
          <p>Findings stay evidence-backed. Catora can prepare an unpublished WordPress draft, but a reviewer must explicitly approve it and WordPress never publishes automatically.</p>
          <div className="service-findings">
            {findings.map((finding) => (
              <article className="service-finding" key={finding.fingerprint}>
                <header><strong>{finding.title}</strong><span>{finding.severity} · {finding.family.replaceAll("_", " ")}</span></header>
                {finding.page_url ? <a href={finding.page_url} rel="noreferrer" target="_blank">{finding.page_url}</a> : <small>Site-wide finding</small>}
                <p>{finding.detail}</p>
                <div className="service-recommendation"><strong>Recommended fix</strong><p>{finding.recommendation}</p></div>
                {finding.evidence[0]?.excerpt ? <blockquote>{finding.evidence[0].excerpt}</blockquote> : null}
                {finding.page_url ? <button disabled={busy} onClick={() => prepareDraft(finding)} type="button">Prepare WordPress draft</button> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {editor ? (
        <section className="service-panel service-draft-editor">
          <h2>Prepare draft: {editor.finding.title}</h2>
          <p><strong>Recommendation:</strong> {editor.finding.recommendation}</p>
          <form className="service-form" onSubmit={saveDraftProposal}>
            <label>Draft page title<input value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} placeholder="Optional replacement page title" /></label>
            <label>Proposed SEO title<input value={editor.metaTitle} onChange={(event) => setEditor({ ...editor, metaTitle: event.target.value })} placeholder="Optional SEO title" /></label>
            <label>Proposed meta description<textarea rows={3} value={editor.metaDescription} onChange={(event) => setEditor({ ...editor, metaDescription: event.target.value })} placeholder="Optional meta description" /></label>
            <label>Proposed page content<textarea rows={10} value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} placeholder="Optional replacement content. Leave blank unless the reviewer has prepared approved copy." /></label>
            <small>Current WordPress revision: {editor.baseRevision}. If the live page changes before delivery, Catora fails closed instead of overwriting the newer revision.</small>
            <button className="primary-button" disabled={busy} type="submit">{busy ? "Working…" : "Prepare proposal"}</button>
          </form>
          {draft ? (
            <div className="service-draft-approval">
              <strong>Proposal status: {draft.status}</strong>
              <p>This creates an unpublished review copy only. It does not modify or publish the live page.</p>
              {draft.status === "pending" ? <button disabled={busy} onClick={() => void approveDraft()} type="button">Approve for WordPress</button> : null}
              {draft.remote_draft_id ? <small>WordPress draft ID: {draft.remote_draft_id}</small> : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
