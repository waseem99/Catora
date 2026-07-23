"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  ShopifyConfiguration,
  ShopifyInstallation,
  disconnectShopifyInstallation,
  getShopifyConfiguration,
  getShopifyInstallation,
  refreshShopifyInstallation,
  startShopifyInstallation,
} from "@/lib/shopify";

type Props = { workspaceId: string };

function date(value: string | null): string {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ShopifyPilotCard({ workspaceId }: Props) {
  const [configuration, setConfiguration] = useState<ShopifyConfiguration | null>(null);
  const [installation, setInstallation] = useState<ShopifyInstallation | null>(null);
  const [shopDomain, setShopDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [config, connected] = await Promise.all([
          getShopifyConfiguration(workspaceId),
          getShopifyInstallation(workspaceId),
        ]);
        if (!active) return;
        setConfiguration(config);
        setInstallation(connected);
        if (connected) setShopDomain(connected.shop_domain);
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Unable to load Shopify status.");
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !shopDomain.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const authorizationUrl = await startShopifyInstallation(workspaceId, shopDomain);
      window.location.assign(authorizationUrl);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start Shopify authorization.");
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      setInstallation(await refreshShopifyInstallation(workspaceId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Shopify reauthorization is required.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!installation || busy) return;
    if (!window.confirm(`Disconnect ${installation.shop_domain} from Catora?`)) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectShopifyInstallation(workspaceId);
      setInstallation({
        ...installation,
        status: "disconnected",
        health: "disconnected",
        detail: "The shop is disconnected and no credential is available.",
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to disconnect Shopify.");
    } finally {
      setBusy(false);
    }
  }

  const configured = configuration?.enabled === true;
  const connected = installation?.status === "active";

  return (
    <article className="onboarding-card pilot-card">
      <span className="path-number">03</span>
      <p className="eyebrow">CONTINUOUS PAID PILOT</p>
      <h2>Connect Shopify</h2>
      <p>
        Authorize Catora’s controlled pilot app with read-only product access. Credentials are
        encrypted at rest and never displayed or returned by the API.
      </p>
      <ul>
        <li>Minimum scope: read_products</li>
        <li>Expiring offline token rotation</li>
        <li>Explicit reconnect and disconnect</li>
      </ul>

      {installation ? (
        <section className={`shopify-connection-state shopify-${installation.health}`}>
          <strong>{installation.shop_domain}</strong>
          <span>{installation.health.replaceAll("_", " ")}</span>
          <p>{installation.detail}</p>
          <small>
            Scopes: {installation.granted_scopes.join(", ") || "none"} · Last refreshed: {date(installation.refreshed_at)}
          </small>
        </section>
      ) : null}

      <form className="shopify-connect-form" onSubmit={connect}>
        <label>
          Permanent Shopify domain
          <input
            value={shopDomain}
            onChange={(event) => setShopDomain(event.target.value)}
            placeholder="store.myshopify.com"
            maxLength={255}
            disabled={busy || connected}
            required
          />
        </label>
        <button
          className="secondary-button path-action"
          type="submit"
          disabled={busy || connected || !configured}
        >
          {busy ? "Working…" : connected ? "Shopify connected" : "Authorize Shopify"}
        </button>
      </form>

      {installation?.health === "refresh_required" ? (
        <button className="secondary-button" type="button" disabled={busy} onClick={refresh}>
          Try credential refresh
        </button>
      ) : null}
      {installation && installation.status !== "disconnected" ? (
        <button className="danger-button" type="button" disabled={busy} onClick={disconnect}>
          Disconnect Shopify
        </button>
      ) : null}

      {!configured ? (
        <small>
          Waiting for the Codistan Shopify Dev Dashboard credentials. The software path is ready;
          authorization remains disabled until those secrets are configured.
        </small>
      ) : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </article>
  );
}
