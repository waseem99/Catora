import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(root, "dist");
const port = Number.parseInt(process.env.PORT || "3001", 10);
const apiOrigin = new URL(process.env.CATORA_API_ORIGIN || "http://localhost:8000");

await new Promise((resolveBuild, rejectBuild) => {
  const child = spawn(process.execPath, [resolve(root, "scripts/build.mjs")], {
    cwd: root,
    stdio: "inherit",
    env: process.env,
  });
  child.once("error", rejectBuild);
  child.once("exit", (code) => {
    if (code === 0) resolveBuild();
    else rejectBuild(new Error(`Shopify App Home build exited with code ${code}`));
  });
});

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host}`);
    if (url.pathname.startsWith("/api/v1/shopify/public/")) {
      const target = new URL(url.pathname + url.search, apiOrigin);
      const body = request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await readBody(request);
      const upstream = await fetch(target, {
        method: request.method,
        headers: {
          accept: request.headers.accept || "application/json",
          authorization: request.headers.authorization || "",
          "content-type": request.headers["content-type"] || "application/json",
        },
        body,
      });
      response.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") || "application/json",
      });
      response.end(Buffer.from(await upstream.arrayBuffer()));
      return;
    }

    const requested = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const candidate = resolve(output, requested);
    const safeCandidate = candidate.startsWith(`${output}/`) ? candidate : resolve(output, "index.html");
    let file = safeCandidate;
    try {
      if (!(await stat(file)).isFile()) file = resolve(output, "index.html");
    } catch {
      file = resolve(output, "index.html");
    }
    response.writeHead(200, {
      "content-type": contentTypes[extname(file)] || "application/octet-stream",
      "cache-control": file.endsWith("index.html") ? "no-store" : "public, max-age=60",
    });
    createReadStream(file).pipe(response);
  } catch (error) {
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end(error instanceof Error ? error.message : "Unexpected server error");
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Shopify App Home listening on http://127.0.0.1:${port}`);
});

function readBody(request) {
  return new Promise((resolveBody, rejectBody) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
    request.on("end", () => resolveBody(Buffer.concat(chunks)));
    request.on("error", rejectBody);
  });
}
