/**
 * HTTP security baseline - M12.6
 * Body limit, security headers and CORS in one place so the server and the negative
 * tests apply exactly the same middleware.
 */

import type { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";
import { cors } from "hono/cors";
import { secureHeaders } from "hono/secure-headers";

export const MAX_BODY_BYTES = 1_000_000;

/** Request headers browsers may send cross-origin: legacy UI, v1 API and A2A. */
export const CORS_ALLOW_HEADERS = [
  "Content-Type",
  "Accept",
  "Authorization",
  "X-Agent-Id",
  "X-User-Id",
  "X-Space-Id",
  "Idempotency-Key",
  "Last-Event-ID",
  "A2A-Version",
] as const;

/** Response headers a browser client needs to read for migration and retry. */
export const CORS_EXPOSE_HEADERS = ["Deprecation", "Link", "Retry-After"] as const;

export function applyHttpSecurity(app: Hono, options: { allowedOrigin: string }): void {
  app.use(
    "*",
    bodyLimit({
      maxSize: MAX_BODY_BYTES,
      onError: (context) =>
        context.json(
          { error: { code: "payload_too_large", message: "Request body is too large" } },
          413,
        ),
    }),
  );
  app.use("*", secureHeaders());
  app.use(
    "*",
    cors({
      // A single exact origin: a wildcard would let any site read authenticated responses.
      origin: options.allowedOrigin,
      allowHeaders: [...CORS_ALLOW_HEADERS],
      exposeHeaders: [...CORS_EXPOSE_HEADERS],
    }),
  );
}
