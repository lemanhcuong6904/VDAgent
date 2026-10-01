import { createHmac, timingSafeEqual } from "node:crypto";

export type WebAuthMode = "demo" | "session";

export interface WebAuthConfig {
  mode: WebAuthMode;
  secret?: string;
  ttlSeconds: number;
}

export interface WebSession {
  userId: string;
  expiresAt: number;
}

const TOKEN_PREFIX = "vdagent.v1";

export function createWebAuth(env: NodeJS.ProcessEnv = process.env): WebAuthConfig {
  const requestedMode = env.WEB_AUTH_MODE?.trim() as WebAuthMode | undefined;
  if (requestedMode && requestedMode !== "session" && requestedMode !== "demo") {
    throw new Error("WEB_AUTH_MODE must be either 'demo' or 'session'");
  }
  const production = env.NODE_ENV === "production";
  const mode: WebAuthMode = requestedMode ? requestedMode : production ? "session" : "demo";
  if (production && mode !== "session") {
    throw new Error("WEB_AUTH_MODE=session is required in production");
  }
  const secret = env.WEB_AUTH_SECRET?.trim();
  if (mode === "session" && (!secret || isPlaceholder(secret) || secret.length < 32)) {
    throw new Error(
      "WEB_AUTH_SECRET must be at least 32 characters and must not be a placeholder in session mode",
    );
  }
  const ttl = Number(env.WEB_SESSION_TTL_SECONDS ?? 86_400);
  return {
    mode,
    secret,
    ttlSeconds: Number.isInteger(ttl) && ttl > 0 ? Math.min(ttl, 2_592_000) : 86_400,
  };
}

export function issueWebSession(
  userId: string,
  config: WebAuthConfig,
  nowSeconds = Math.floor(Date.now() / 1000),
): string {
  if (!/^[a-zA-Z0-9._:-]{1,128}$/.test(userId)) throw new Error("Invalid web user id");
  if (!config.secret || isPlaceholder(config.secret)) {
    throw new Error("Web session signing secret is not configured");
  }
  const expiresAt = nowSeconds + config.ttlSeconds;
  const payload = `${TOKEN_PREFIX}.${userId}.${expiresAt}`;
  return `${payload}.${signature(payload, config.secret)}`;
}

export function verifyWebSession(
  token: string | undefined,
  config: WebAuthConfig,
  nowSeconds = Math.floor(Date.now() / 1000),
): WebSession | undefined {
  if (!token || !config.secret || isPlaceholder(config.secret)) return undefined;
  const parts = token.split(".");
  if (parts.length !== 5 || parts[0] !== "vdagent" || parts[1] !== "v1") return undefined;
  const userId = parts[2];
  const expiresAt = Number(parts[3]);
  if (!/^[a-zA-Z0-9._:-]{1,128}$/.test(userId) || !Number.isSafeInteger(expiresAt)) {
    return undefined;
  }
  if (expiresAt <= nowSeconds || expiresAt - nowSeconds > 2_592_000) return undefined;
  const expected = signature(`${TOKEN_PREFIX}.${userId}.${expiresAt}`, config.secret);
  const presented = parts[4];
  if (expected.length !== presented.length) return undefined;
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(presented))) return undefined;
  return { userId, expiresAt };
}

export function bearerToken(authorization: string | undefined): string | undefined {
  const match = authorization?.match(/^Bearer\s+([^\s]+)$/i);
  return match?.[1];
}

function signature(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

function isPlaceholder(value: string): boolean {
  return /^(?:replace-with|change-me|development|placeholder|secret)$/i.test(value);
}
