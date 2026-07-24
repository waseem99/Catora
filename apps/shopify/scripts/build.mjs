import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, "src");
const output = resolve(root, "dist");
const apiKey = process.env.SHOPIFY_API_KEY?.trim() || "development-unlinked";
const requireLinkedKey =
  process.env.VERCEL_ENV === "production" ||
  process.env.CATORA_REQUIRE_SHOPIFY_API_KEY === "true";

if (requireLinkedKey && !/^[A-Za-z0-9_-]{8,}$/.test(apiKey)) {
  throw new Error(
    "SHOPIFY_API_KEY must contain the linked public app client ID for a production build.",
  );
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

const template = await readFile(resolve(source, "index.html"), "utf8");
const html = template.replaceAll("__SHOPIFY_API_KEY__", apiKey);
if (html.includes("__SHOPIFY_API_KEY__")) {
  throw new Error("The Shopify API key placeholder was not replaced.");
}

await writeFile(resolve(output, "index.html"), html, "utf8");
for (const file of ["app.js", "state.js", "styles.css"]) {
  await cp(resolve(source, file), resolve(output, file));
}

console.log(`Built Shopify App Home in ${output}`);
