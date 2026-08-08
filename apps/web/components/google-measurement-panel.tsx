"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  connectGoogleMeasurement,
  listMeasurementAccounts,
  syncGoogleMeasurement,
  type GoogleMeasurementSync,
  type MeasurementAccount,
} from "@/lib/measurement";

type Props = { workspaceId: string };

const DEFAULT_CREDENTIAL_REFERENCE = "env:CATORA_GOOGLE_MEASUREMENT_SERVICE_ACCOUNT_JSON";

export function GoogleMeasurementPanel({ workspaceId }: Props) {
  const [accounts, setAccounts] = useState<MeasurementAccount[]>([]);
  const [provider, setProvider] = useState<"google_search_console" | "ga4">(
    "google_search_console",
  );
  const [credentialReference, setCredentialReference] = useState(
    DEFAULT_CREDENTIAL_REFERENCE,
  );
  const [propertyId, setPropertyId] = useState("");
  const [result, setResult] = useState<GoogleMeasurementSync | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setAccounts(await listMeasurementAccounts(workspaceId));
    } catch {
      // Measurement can remain disabled until the Railway runtime is explicitly enabled.
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await connectGoogleMeasurement(workspaceId, {
        provider,
        credential_reference: credentialReference.trim(),
        property_allowlist: [propertyId.trim()],
      });
      setResult(next);
      setPropertyId("");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to connect Google measurement.");
    } finally {
      setBusy(false);
    }
  }

  async function sync(account: MeasurementAccount) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await syncGoogleMeasurement(workspaceId, account.id);
      setResult(next);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to synchronize Google measurement.");
    } finally {
      setBusy(false);
    }
  }

  const googleAccounts = accounts.filter((account) =>
    ["google_search_console", "ga4"].includes(account.provider),
  );

  return (
    <section className="shell service-visibility-shell" aria-labelledby="google-measurement-heading">
      <article className="service-panel">
        <div>
          <p className="eyebrow">OUTCOME MEASUREMENT</p>
          <h2 id="google-measurement-heading">Connect Search Console and GA4</h2>
          <p className="lede">
            Catora imports read-only aggregate search and traffic observations for the exact
            properties you approve. The Google service-account key stays in Railway; this form
            stores only its environment-variable reference.
          </p>
        </div>

        {error ? <p className="service-error">{error}</p> : null}
        {result ? (
          <p className="service-notice">
            {result.provider === "google_search_console" ? "Search Console" : "GA4"} synced:
            {` ${result.properties} property, ${result.accepted} new observations, ${result.duplicate} duplicates.`}
          </p>
        ) : null}

        <div className="service-grid">
          <form className="service-form" onSubmit={connect}>
            <label>
              Provider
              <select
                value={provider}
                onChange={(event) => {
                  setProvider(event.target.value as typeof provider);
                  setPropertyId("");
                }}
              >
                <option value="google_search_console">Google Search Console</option>
                <option value="ga4">Google Analytics 4</option>
              </select>
            </label>
            <label>
              Railway credential reference
              <input
                required
                pattern="env:[A-Z][A-Z0-9_]{2,100}"
                value={credentialReference}
                onChange={(event) => setCredentialReference(event.target.value)}
              />
            </label>
            <label>
              {provider === "google_search_console" ? "Search Console property" : "GA4 property ID"}
              <input
                required
                value={propertyId}
                onChange={(event) => setPropertyId(event.target.value)}
                placeholder={
                  provider === "google_search_console"
                    ? "sc-domain:example.com"
                    : "123456789"
                }
              />
              <small>
                {provider === "google_search_console"
                  ? "Use the exact property identifier shown in Search Console."
                  : "Use the numeric GA4 property ID, not the G- measurement ID."}
              </small>
            </label>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Working…" : "Verify access and connect"}
            </button>
          </form>

          <div className="service-list">
            <h3>Connected measurement accounts</h3>
            {googleAccounts.length === 0 ? (
              <p>No Google measurement account has passed live property verification yet.</p>
            ) : googleAccounts.map((account) => (
              <div className="service-source" key={account.id}>
                <div>
                  <strong>
                    {account.provider === "google_search_console" ? "Search Console" : "GA4"}
                  </strong>
                  <span>{account.external_account_id}</span>
                  <small>{account.status} · daily sync scheduled</small>
                </div>
                <button disabled={busy} onClick={() => void sync(account)} type="button">
                  Sync now
                </button>
              </div>
            ))}
          </div>
        </div>
      </article>
    </section>
  );
}
