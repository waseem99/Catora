"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  ShopifyConfiguration,
  ShopifyInstallation,
  ShopifyWebhookDelivery,
  disconnectShopifyInstallation,
  getLatestShopifyWebhook,
  getShopifyConfiguration,
  getShopifyInstallation,
  refreshShopifyInstallation,
  startShopifyInstallation,
  syncShopifyInstallation,
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
  const [latestWebhook, setLatestWebhook] = useState<ShopifyWebhookDelivery | null>(null);
  const [shopDomain, setShopDomain] = useState("northstar-living-demo.myshopify.com");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const installationStatus = installation?.status;

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [config, connected, webhook] = await Promise.all([
          getShopifyConfiguration(workspaceId),
          getShopifyInstallation(workspaceId),
          getLatestShopifyWebhook(workspaceId),
        ]);
        if (!active) return;
        setConfiguration(config);
        setInstallation(connected);
        setLatestWebhook(webhook);
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

  useEffect(() => {
    if (installationStatus !== "active") return;
    const timer = window.setInterval(() => {
      void Promise.all([
        getShopifyInstallation(workspaceId),
        getLatestShopifyWebhook(workspaceId),
      ])
        .then(([connected, webhook]) => {
          setInstallation(connected);
          setLatestWebhook(webhook);
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [installationStatus, workspaceId]);

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

  async function syncNow() {
    setBusy(true);
    setError(null);
    try {
      setInstallation(await syncShopifyInstallation(workspaceId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start Shopify synchronization.");
    } finally {
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
        sync_status: "revoked",
        detail: "The shop is disconnected and no credential is available.",
      });
      setLatestWebhook(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to disconnect Shopify.");
    } finally {
      setBusy(false);
    }
  }

  const configured = configuration?.enabled === true;
  const connected = installation?.status === "active";
  const syncing = installation
    ? ["queued", "coalesced", "running"].includes(installation.sync_status)
    : false;

  return (
    <article className="onboarding-card pilot-card">
      <span className="path-number">03</span>
      <p className="eyebrow">CONTINUOUS PAID PILOT</p>
      <h2>Connect Shopify</h2>
      <p>
        Authorize Catora’s controlled pilot app with read-only product access. Installation starts
        a real catalog sync, deterministic audit and webhook-monitored update cycle.
      </p>
      <ul>
        <li>Minimum scope: read_products</li>
        <li>Verified create, update, delete and uninstall webhooks</li>
        <li>Encrypted expiring offline-token rotation</li>
      </ul>

      {installation ? (
        <section className={`shopify-connection-state shopify-${installation.health}`}>
          <header>
            <strong>{installation.shop_domain}</strong>
            <span>{installation.health.replaceAll("_", " ")}</span>
          </header>
          <p>{installation.detail}</p>
          <div className="shopify-sync-metrics">
            <div><span>Products</span><strong>{installation.product_count.toLocaleString()}</strong></div>
            <div><span>Variants</span><strong>{installation.variant_count.toLocaleString()}</strong></div>
            <div><span>Warnings</span><strong>{installation.warning_count.toLocaleString()}</strong></div>
          </div>
          <small>
            Sync: {installation.sync_status.replaceAll("_", " ")} · Last verified: {date(installation.last_successful_sync_at)}
          </small>
          {latestWebhook ? (
            <div className={`shopify-webhook-proof webhook-${latestWebhook.status}`}>
              <strong>Latest verified webhook</strong>
              <span>{latestWebhook.topic}</span>
              <small>
                HMAC verified · {latestWebhook.status} · Received {date(latestWebhook.received_at)}
              </small>
              {latestWebhook.product_id ? (
                <small>Shopify product ID: {latestWebhook.product_id}</small>
              ) : null}
            </div>
          ) : (
            <small>No verified Shopify webhook has been received yet.</small>
          )}
          {installation.last_sync_error_type ? (
            <small className="form-error">Last sync stopped safely: {installation.last_sync_error_type}</small>
          ) : null}
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

      {connected ? (
        <button className="primary-button" type="button" disabled={busy || syncing} onClick={syncNow}>
          {syncing ? "Catalog synchronization running…" : "Sync catalog now"}
        </button>
      ) : null}
      {installation?.health === "refresh_required" ? (
        <button className="secondary-button" type="button" disabled={busy} onClick={refresh}>
          Try credential refresh
        </button>
      ) : null}
      {installation && installation.status !== "disconnected" && installation.status !== "revoked" ? (
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
