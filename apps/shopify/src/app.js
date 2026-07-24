import {
  apiErrorMessage,
  formatTimestamp,
  installationLabel,
  installationTone,
  isActiveSync,
  safeShopDomain,
  syncLabel,
  syncTone,
  taxonomyCoverage,
} from "./state.js";

const endpoints = {
  session: "/api/v1/shopify/public/session",
  activate: "/api/v1/shopify/public/activate",
  installation: "/api/v1/shopify/public/installation",
  sync: "/api/v1/shopify/public/installation/sync",
};

const elements = {
  loadingView: document.querySelector("#loading-view"),
  activationView: document.querySelector("#activation-view"),
  dashboardView: document.querySelector("#dashboard-view"),
  errorBanner: document.querySelector("#error-banner"),
  errorMessage: document.querySelector("#error-message"),
  retryAction: document.querySelector("#retry-action"),
  activateAction: document.querySelector("#activate-action"),
  invitedStore: document.querySelector("#invited-store"),
  syncAction: document.querySelector("#sync-action"),
  inlineSyncAction: document.querySelector("#inline-sync-action"),
  installationBadge: document.querySelector("#installation-badge"),
  syncBadge: document.querySelector("#sync-badge"),
  storeDomain: document.querySelector("#store-domain"),
  lastSync: document.querySelector("#last-sync"),
  syncBanner: document.querySelector("#sync-banner"),
  reauthorizeBanner: document.querySelector("#reauthorize-banner"),
  syncErrorBanner: document.querySelector("#sync-error-banner"),
  syncErrorMessage: document.querySelector("#sync-error-message"),
  productCount: document.querySelector("#product-count"),
  variantCount: document.querySelector("#variant-count"),
  warningCount: document.querySelector("#warning-count"),
  coveragePercent: document.querySelector("#coverage-percent"),
  assignedCount: document.querySelector("#assigned-count"),
  ambiguousCount: document.querySelector("#ambiguous-count"),
  unclassifiedCount: document.querySelector("#unclassified-count"),
  workspaceReference: document.querySelector("#workspace-reference"),
  liveStatus: document.querySelector("#live-status"),
};

let pollTimer = null;
let requestInFlight = false;

class ApiRequestError extends Error {
  constructor(status, payload) {
    super(apiErrorMessage(payload));
    this.name = "ApiRequestError";
    this.status = status;
    this.payload = payload;
  }
}

function setHidden(element, hidden) {
  if (!element) return;
  element.hidden = hidden;
}

function setBusy(button, busy) {
  if (!button) return;
  button.toggleAttribute("loading", busy);
  button.toggleAttribute("disabled", busy);
}

function announce(message) {
  if (elements.liveStatus) elements.liveStatus.textContent = message;
}

function toast(message, options = {}) {
  const app = globalThis.shopify;
  if (app?.toast?.show) app.toast.show(message, options);
}

async function sessionToken() {
  const app = globalThis.shopify;
  if (!app?.idToken) {
    throw new ApiRequestError(401, {
      detail: "Open Catora from the Apps area of Shopify admin to authenticate this store.",
    });
  }
  const token = await app.idToken();
  if (typeof token !== "string" || !token) {
    throw new ApiRequestError(401, {
      detail: "Shopify did not provide an authenticated app session. Reopen Catora in Shopify admin.",
    });
  }
  return token;
}

async function apiRequest(path, options = {}) {
  const token = await sessionToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };
  if (!response.ok) throw new ApiRequestError(response.status, payload);
  return payload;
}

function showLoading() {
  clearPoll();
  setHidden(elements.loadingView, false);
  setHidden(elements.activationView, true);
  setHidden(elements.dashboardView, true);
  setHidden(elements.errorBanner, true);
  setHidden(elements.syncAction, true);
}

function showError(error) {
  clearPoll();
  setHidden(elements.loadingView, true);
  setHidden(elements.activationView, true);
  setHidden(elements.dashboardView, true);
  setHidden(elements.syncAction, true);
  if (elements.errorMessage) {
    const fallback =
      error instanceof ApiRequestError && error.status === 401
        ? "Open Catora from Shopify admin to authenticate this store."
        : "Catora could not load this Shopify installation.";
    elements.errorMessage.textContent = apiErrorMessage(error?.payload, fallback);
  }
  setHidden(elements.errorBanner, false);
  announce("Catora needs attention.");
}

function showActivation(session) {
  clearPoll();
  setHidden(elements.loadingView, true);
  setHidden(elements.dashboardView, true);
  setHidden(elements.errorBanner, true);
  setHidden(elements.syncAction, true);
  setHidden(elements.activationView, false);
  if (elements.invitedStore) {
    elements.invitedStore.textContent = `Invited store: ${safeShopDomain(session.shop_domain)}`;
  }
  announce("This invited Shopify store is ready to connect.");
}

function setBadge(element, label, tone) {
  if (!element) return;
  element.textContent = label;
  element.setAttribute("tone", tone);
}

function renderInstallation(status) {
  setHidden(elements.loadingView, true);
  setHidden(elements.activationView, true);
  setHidden(elements.errorBanner, true);
  setHidden(elements.dashboardView, false);

  const syncing = isActiveSync(status.sync_status);
  const canSync = status.installation_status === "active" && !syncing;
  setHidden(elements.syncAction, false);
  setBusy(elements.syncAction, syncing);
  setBusy(elements.inlineSyncAction, syncing);
  elements.syncAction?.toggleAttribute("disabled", !canSync);
  elements.inlineSyncAction?.toggleAttribute("disabled", !canSync);

  setBadge(
    elements.installationBadge,
    installationLabel(status.installation_status),
    installationTone(status.installation_status),
  );
  setBadge(elements.syncBadge, syncLabel(status.sync_status), syncTone(status.sync_status));

  if (elements.storeDomain) {
    elements.storeDomain.textContent = safeShopDomain(status.shop_domain);
  }
  if (elements.lastSync) {
    elements.lastSync.textContent = `Last successful sync: ${formatTimestamp(
      status.last_successful_sync_at,
      document.documentElement.lang || "en-US",
    )}`;
  }

  setHidden(elements.syncBanner, !syncing);
  setHidden(elements.reauthorizeBanner, !status.reauthorization_required);
  setHidden(elements.syncErrorBanner, status.sync_status !== "failed");
  if (elements.syncErrorMessage && status.last_sync_error_type) {
    elements.syncErrorMessage.textContent =
      "Catora could not complete the latest synchronization. Retry the sync; if it fails again, contact Catora support with this error: " +
      status.last_sync_error_type;
  }

  const coverage = taxonomyCoverage(status);
  if (elements.productCount) elements.productCount.textContent = String(status.product_count ?? 0);
  if (elements.variantCount) elements.variantCount.textContent = String(status.variant_count ?? 0);
  if (elements.warningCount) elements.warningCount.textContent = String(status.warning_count ?? 0);
  if (elements.coveragePercent) elements.coveragePercent.textContent = `${coverage.percentage}%`;
  if (elements.assignedCount) elements.assignedCount.textContent = String(coverage.assigned);
  if (elements.ambiguousCount) elements.ambiguousCount.textContent = String(coverage.ambiguous);
  if (elements.unclassifiedCount) {
    elements.unclassifiedCount.textContent = String(coverage.unclassified);
  }
  if (elements.workspaceReference) {
    elements.workspaceReference.textContent = `Isolated workspace: ${status.workspace_id}`;
  }

  announce(`Catalog status: ${syncLabel(status.sync_status)}.`);
  if (syncing) schedulePoll();
  else clearPoll();
}

async function loadInstallation() {
  const status = await apiRequest(endpoints.installation);
  renderInstallation(status);
}

async function bootstrap() {
  if (requestInFlight) return;
  requestInFlight = true;
  showLoading();
  try {
    const session = await apiRequest(endpoints.session);
    if (session.invitation_status === "pending") showActivation(session);
    else await loadInstallation();
  } catch (error) {
    showError(error);
  } finally {
    requestInFlight = false;
  }
}

async function activate() {
  if (requestInFlight) return;
  requestInFlight = true;
  setBusy(elements.activateAction, true);
  announce("Connecting the invited Shopify catalog.");
  try {
    await apiRequest(endpoints.activate, { method: "POST" });
    toast("Catora connected this Shopify catalog");
    await loadInstallation();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(elements.activateAction, false);
    requestInFlight = false;
  }
}

async function sync() {
  if (requestInFlight) return;
  requestInFlight = true;
  setBusy(elements.syncAction, true);
  setBusy(elements.inlineSyncAction, true);
  announce("Queueing a Shopify catalog synchronization.");
  try {
    const status = await apiRequest(endpoints.sync, { method: "POST" });
    renderInstallation(status);
    toast("Catalog synchronization queued");
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 409) {
      toast(apiErrorMessage(error.payload), { isError: true });
      await loadInstallation();
    } else {
      showError(error);
    }
  } finally {
    requestInFlight = false;
  }
}

function clearPoll() {
  if (pollTimer !== null) globalThis.clearTimeout(pollTimer);
  pollTimer = null;
}

function schedulePoll() {
  clearPoll();
  pollTimer = globalThis.setTimeout(async () => {
    if (document.visibilityState !== "visible" || requestInFlight) {
      schedulePoll();
      return;
    }
    try {
      await loadInstallation();
    } catch (error) {
      showError(error);
    }
  }, 5000);
}

elements.retryAction?.addEventListener("click", bootstrap);
elements.activateAction?.addEventListener("click", activate);
elements.syncAction?.addEventListener("click", sync);
elements.inlineSyncAction?.addEventListener("click", sync);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !requestInFlight) bootstrap();
});

bootstrap();
