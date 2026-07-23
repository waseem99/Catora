"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, type AuthUser } from "@/lib/auth";
import {
  DemoPreflightSchema,
  DemoResetResponseSchema,
  DemoResetStatusSchema,
  demoPreflightPath,
  demoResetPath,
  demoResetStatusPath,
  type DemoPreflight,
} from "@/lib/demo";

type Props = { workspaceId: string };

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function PresenterReadiness({ workspaceId }: Props) {
  const [allowed, setAllowed] = useState(false);
  const [preflight, setPreflight] = useState<DemoPreflight | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const user = await apiRequest<AuthUser>("/api/v1/auth/me");
      const membership = user.memberships.find((item) => item.workspace_id === workspaceId);
      const canPresent = membership?.role === "owner" || membership?.role === "admin";
      setAllowed(canPresent);
      if (!canPresent) {
        setPreflight(null);
        return;
      }
      const payload = await apiRequest<unknown>(demoPreflightPath(workspaceId));
      setPreflight(DemoPreflightSchema.parse(payload));
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Unable to run presenter preflight");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function resetDemo() {
    const confirmed = window.confirm(
      "Reset the dedicated Northstar sales demo? This replaces only the sales-demo workspace.",
    );
    if (!confirmed) return;
    setResetting(true);
    setError(null);
    setNotice("Reset queued. The previous verified snapshot remains available while it runs.");
    try {
      const payload = await apiRequest<unknown>(demoResetPath(workspaceId), {
        method: "POST",
        body: JSON.stringify({ reason: "Presenter reset before a client demonstration" }),
      });
      const reset = DemoResetResponseSchema.parse(payload);
      for (let attempt = 0; attempt < 300; attempt += 1) {
        await wait(2_000);
        const statusPayload = await apiRequest<unknown>(
          demoResetStatusPath(workspaceId, reset.task_id),
        );
        const status = DemoResetStatusSchema.parse(statusPayload);
        setNotice(status.detail);
        if (status.status === "completed") {
          await load();
          window.location.reload();
          return;
        }
        if (status.status === "failed") {
          throw new Error(status.detail);
        }
      }
      throw new Error("The reset is still running. Check presenter preflight before the meeting.");
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Unable to reset the client demo");
    } finally {
      setResetting(false);
    }
  }

  if (!allowed && !loading) return null;

  return (
    <section className="presenter-panel" aria-labelledby="presenter-readiness-title">
      <div className="presenter-panel-heading">
        <div>
          <p className="eyebrow">PRESENTER CONTROL</p>
          <h2 id="presenter-readiness-title">Demo readiness</h2>
        </div>
        {preflight ? (
          <span className={preflight.ready ? "presenter-ready" : "presenter-warning"}>
            {preflight.ready ? "Ready to present" : "Using verified fallback"}
          </span>
        ) : null}
      </div>

      {loading ? <p className="loading-state">Checking the hosted demo…</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="success-banner" role="status">{notice}</p> : null}

      {preflight ? (
        <>
          <div className="presenter-snapshot">
            <strong>
              {preflight.last_verified_snapshot.product_count.toLocaleString()} products ·{" "}
              {preflight.last_verified_snapshot.variant_count.toLocaleString()} SKUs
            </strong>
            <span>
              Last verified {new Date(preflight.last_verified_snapshot.verified_at).toLocaleString()}
            </span>
          </div>
          {!preflight.ready ? (
            <p className="presenter-fallback-note">
              Live readiness is incomplete. The persisted, timestamped verified analysis remains
              available for the demonstration.
            </p>
          ) : null}
          <div className="presenter-components">
            {preflight.components.map((component) => (
              <article className={`presenter-component presenter-${component.state}`} key={component.key}>
                <div>
                  <strong>{component.label}</strong>
                  <span>{component.detail}</span>
                </div>
                <b>{component.state}</b>
              </article>
            ))}
          </div>
          <div className="presenter-actions">
            <button className="secondary-button" onClick={() => void load()} type="button">
              Run preflight again
            </button>
            <button
              className="primary-button"
              disabled={resetting}
              onClick={() => void resetDemo()}
              type="button"
            >
              {resetting ? "Resetting demo…" : "Reset demo workspace"}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
