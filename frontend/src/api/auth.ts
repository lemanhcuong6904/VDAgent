/** Runtime auth material supplied by the identity gateway after it authenticates a user. */
export interface BrowserAuthConfig {
  webSessionToken?: string;
}

declare global {
  interface Window {
    /** A short-lived web session only; never put signing secrets or operator tokens here. */
    __VDAGENT_AUTH__?: BrowserAuthConfig;
  }
}

/** Read on every request so a gateway can rotate the short-lived token without reloading. */
export function getWebSessionToken(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const token = window.__VDAGENT_AUTH__?.webSessionToken?.trim();
  return token || undefined;
}

/** Use the signed session when present; X-User-Id is only a local demo-mode fallback. */
export function browserAuthHeaders(userId: string | null): Record<string, string> {
  const token = getWebSessionToken();
  if (token) return { Authorization: `Bearer ${token}` };
  return userId ? { "X-User-Id": userId } : {};
}
