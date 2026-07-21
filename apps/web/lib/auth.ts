const apiUrl = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";

export type RoleName = "owner" | "admin" | "analyst" | "reviewer" | "viewer";

export type WorkspaceMembership = {
  workspace_id: string;
  organization_id: string;
  workspace_name: string;
  organization_name: string;
  role: RoleName;
};

export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  memberships: WorkspaceMembership[];
};

export type Member = {
  membership_id: string;
  user_id: string;
  email: string;
  display_name: string;
  role: RoleName;
};

export function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const prefix = "catora_csrf=";
  const cookie = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const csrf = csrfToken();
  if (csrf && init.method && !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())) {
    headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
