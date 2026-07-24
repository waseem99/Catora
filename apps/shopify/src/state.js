export const ACTIVE_SYNC_STATES = new Set(["queued", "coalesced", "running"]);

export function isActiveSync(status) {
  return ACTIVE_SYNC_STATES.has(status);
}

export function syncLabel(status) {
  const labels = {
    not_started: "Not started",
    queued: "Queued",
    coalesced: "Queued",
    running: "Syncing",
    completed: "Up to date",
    failed: "Needs attention",
  };
  return labels[status] ?? "Unknown";
}

export function syncTone(status) {
  if (status === "completed") return "success";
  if (status === "failed") return "critical";
  if (isActiveSync(status)) return "info";
  return "neutral";
}

export function installationLabel(status) {
  const labels = {
    active: "Connected",
    refresh_required: "Reconnect required",
    disconnected: "Disconnected",
    failed: "Needs attention",
  };
  return labels[status] ?? "Unknown";
}

export function installationTone(status) {
  if (status === "active") return "success";
  if (status === "refresh_required" || status === "failed") return "critical";
  return "neutral";
}

export function formatTimestamp(value, locale = "en-US") {
  if (!value) return "Not yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export function taxonomyCoverage(status) {
  const assigned = nonNegativeInteger(status?.assigned_category_count);
  const ambiguous = nonNegativeInteger(status?.ambiguous_category_count);
  const unclassified = nonNegativeInteger(status?.unclassified_category_count);
  const total = assigned + ambiguous + unclassified;
  return {
    assigned,
    ambiguous,
    unclassified,
    total,
    percentage: total === 0 ? 0 : Math.round((assigned / total) * 100),
  };
}

export function nonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

export function apiErrorMessage(error, fallback = "Catora could not complete the request.") {
  if (error && typeof error === "object") {
    const detail = error.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
  }
  return fallback;
}

export function safeShopDomain(value) {
  if (typeof value !== "string") return "Shopify store";
  return /^[a-z0-9][a-z0-9-]*\.myshopify\.com$/i.test(value)
    ? value.toLowerCase()
    : "Shopify store";
}
