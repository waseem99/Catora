import assert from "node:assert/strict";
import test from "node:test";

import {
  apiErrorMessage,
  formatTimestamp,
  installationLabel,
  isActiveSync,
  safeShopDomain,
  syncLabel,
  syncTone,
  taxonomyCoverage,
} from "../src/state.js";

test("active synchronization states are bounded", () => {
  assert.equal(isActiveSync("queued"), true);
  assert.equal(isActiveSync("coalesced"), true);
  assert.equal(isActiveSync("running"), true);
  assert.equal(isActiveSync("completed"), false);
  assert.equal(isActiveSync("unknown"), false);
});

test("merchant-facing status labels fail safely", () => {
  assert.equal(syncLabel("completed"), "Up to date");
  assert.equal(syncTone("failed"), "critical");
  assert.equal(installationLabel("refresh_required"), "Reconnect required");
  assert.equal(syncLabel("unexpected"), "Unknown");
});

test("taxonomy coverage ignores invalid counters", () => {
  assert.deepEqual(
    taxonomyCoverage({
      assigned_category_count: 8,
      ambiguous_category_count: 1,
      unclassified_category_count: 1,
    }),
    {
      assigned: 8,
      ambiguous: 1,
      unclassified: 1,
      total: 10,
      percentage: 80,
    },
  );
  assert.deepEqual(taxonomyCoverage({ assigned_category_count: -2 }), {
    assigned: 0,
    ambiguous: 0,
    unclassified: 0,
    total: 0,
    percentage: 0,
  });
});

test("shop domains and API errors are not rendered blindly", () => {
  assert.equal(safeShopDomain("Prospect-Store.myshopify.com"), "prospect-store.myshopify.com");
  assert.equal(safeShopDomain("javascript:alert(1)"), "Shopify store");
  assert.equal(apiErrorMessage({ detail: "Invitation expired" }), "Invitation expired");
  assert.equal(apiErrorMessage({ detail: { unsafe: true } }, "Fallback"), "Fallback");
});

test("timestamps use a stable fallback", () => {
  assert.equal(formatTimestamp(null), "Not yet");
  assert.equal(formatTimestamp("not-a-date"), "Unavailable");
  assert.match(formatTimestamp("2026-07-24T12:00:00Z", "en-US"), /2026/);
});
