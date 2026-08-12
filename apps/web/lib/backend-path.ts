export const backendProxyPrefix = "/api/backend";

export function backendApiPath(path: string): string {
  if (!path.startsWith("/")) {
    throw new Error("Backend API path must start with /");
  }
  return `${backendProxyPrefix}${path}`;
}
