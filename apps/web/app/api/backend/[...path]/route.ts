import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const hopByHopHeaders = new Set([
  "connection",
  "content-length",
  "content-encoding",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function runtimeApiOrigin(): string {
  const raw =
    process.env.CATORA_API_URL?.trim() ||
    process.env.NEXT_PUBLIC_CATORA_API_URL?.trim() ||
    "http://localhost:8000";
  return raw.replace(/\/+$/, "");
}

function forwardedHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  for (const [key, value] of request.headers.entries()) {
    if (!hopByHopHeaders.has(key.toLowerCase())) headers.append(key, value);
  }
  headers.set("x-forwarded-host", request.nextUrl.host);
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  for (const [key, value] of upstream.headers.entries()) {
    const normalized = key.toLowerCase();
    if (normalized === "set-cookie" || hopByHopHeaders.has(normalized)) continue;
    headers.append(key, value);
  }

  const cookieHeaders = upstream.headers as Headers & {
    getSetCookie?: () => string[];
  };
  const cookies = cookieHeaders.getSetCookie?.() ?? [];
  if (cookies.length > 0) {
    for (const cookie of cookies) headers.append("set-cookie", cookie);
  } else {
    const cookie = upstream.headers.get("set-cookie");
    if (cookie) headers.append("set-cookie", cookie);
  }
  headers.set("cache-control", "no-store");
  return headers;
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { path } = await context.params;
  const upstream = new URL(`${runtimeApiOrigin()}/${path.map(encodeURIComponent).join("/")}`);
  upstream.search = request.nextUrl.search;

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(upstream, {
    method,
    headers: forwardedHeaders(request),
    body,
    cache: "no-store",
    redirect: "manual",
  });

  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders(response),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
