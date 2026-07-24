import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const files = {
  html: await readFile(resolve(root, "src/index.html"), "utf8"),
  app: await readFile(resolve(root, "src/app.js"), "utf8"),
  state: await readFile(resolve(root, "src/state.js"), "utf8"),
  vercel: await readFile(resolve(root, "vercel.json"), "utf8"),
};
const errors = [];

function requireText(name, value, expected) {
  if (!value.includes(expected)) errors.push(`${name} must include ${expected}`);
}

requireText("index.html", files.html, 'name="shopify-api-key"');
requireText(
  "index.html",
  files.html,
  "https://cdn.shopify.com/shopifycloud/app-bridge.js",
);
requireText(
  "index.html",
  files.html,
  "https://cdn.shopify.com/shopifycloud/polaris.js",
);
requireText("index.html", files.html, "<s-page");
requireText("index.html", files.html, "<s-section");
requireText("index.html", files.html, 'id="analysis-badge"');
requireText("index.html", files.html, 'id="report-action"');
requireText("index.html", files.html, 'id="backlog-action"');
requireText("app.js", files.app, "globalThis.shopify");
requireText("app.js", files.app, ".idToken()");
requireText("app.js", files.app, "/api/v1/shopify/public/session");
requireText("app.js", files.app, "/api/v1/shopify/public/activate");
requireText("app.js", files.app, "/api/v1/shopify/public/installation/sync");
requireText("app.js", files.app, "/api/v1/shopify/public/report.pptx");
requireText("app.js", files.app, "/api/v1/shopify/public/backlog.csv");
requireText("app.js", files.app, "Authorization: `Bearer ${token}`");
requireText("vercel.json", files.vercel, "https://api.catora.codistan.org");
requireText("vercel.json", files.vercel, "frame-ancestors");

const serialized = Object.values(files).join("\n").toLowerCase();
for (const forbidden of [
  "shpat_",
  "shprt_",
  "client_secret",
  "refresh_token",
  "access_token",
  "localstorage",
  "sessionstorage",
  "document.cookie",
  "write_products",
]) {
  if (serialized.includes(forbidden)) {
    errors.push(`Embedded app source contains forbidden marker ${forbidden}`);
  }
}

const endpointMatches = files.app.matchAll(/["'`]\/api\/v1\/([^"'`]+)["'`]/g);
for (const match of endpointMatches) {
  if (!match[1].startsWith("shopify/public/")) {
    errors.push(`Embedded app calls an unapproved API path: /api/v1/${match[1]}`);
  }
}

let vercel;
try {
  vercel = JSON.parse(files.vercel);
} catch (error) {
  errors.push(`vercel.json is invalid JSON: ${error.message}`);
}
if (vercel && vercel.outputDirectory !== "dist") {
  errors.push("vercel.json outputDirectory must be dist");
}

if (errors.length) {
  for (const error of errors) console.error(`[error] ${error}`);
  process.exitCode = 1;
} else {
  console.log("Shopify App Home contract: valid");
}
