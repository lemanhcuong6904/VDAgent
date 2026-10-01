# Browser/API security negatives and event compatibility — M12.6

**Status**: ✅ Completed
**Modules**: `src/http-security.ts` (`applyHttpSecurity`), `frontend/src/events/parseEvent.ts`
**Tests**: `test/security-negatives.test.ts` (15), `frontend/src/events/parseEvent.test.ts` (7)

Each test states an attack or a compatibility drift and shows it fails closed. The server and
the tests mount the same `applyHttpSecurity`, so the tests cannot drift from production.

## HTTP baseline

`applyHttpSecurity` replaces three inline `app.use` calls in `src/server.ts`:

- **Body limit** 1,000,000 bytes. An oversized body now gets `413 payload_too_large` in the
  standard envelope, before any handler or query runs.
- **Security headers** (`hono/secure-headers`): `X-Frame-Options: SAMEORIGIN`,
  `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`.
- **CORS** allows a single exact origin (`WEB_ALLOWED_ORIGIN`), never `*`. Allowed request
  headers now include the ones M12 added (`X-Space-Id`, `Idempotency-Key`, `Last-Event-ID`,
  `A2A-Version`); before this, a browser client on another origin could not send them. The
  migration headers `Deprecation`, `Link` and `Retry-After` are exposed.

## Negatives covered

| Attack | Result |
| --- | --- |
| Expired session | `401`, no query |
| User id swapped inside a signed session | `401`, no query |
| Session signed with another secret | `401` |
| Session passed as `?token=` / `?access_token=` | `401`; tokens are accepted only in `Authorization`, so they never land in access logs |
| `X-User-Id` impersonation in `session` mode | `401` on both `/api/*` and `/api/v1/*` |
| Foreign origin reading an API response | No matching `Access-Control-Allow-Origin` |
| Oversized body | `413` before any handler |
| `X-Space-Id` carrying SQL or path syntax | `401`; the run query is never reached |
| HTML artifact opened from the API origin | Served as `attachment`, `application/octet-stream`, `nosniff`, `CSP: sandbox` |
| Raw HTML or `<script>` in agent markdown | Escaped |
| `javascript:` / `data:` links in agent markdown | `href` neutralised |
| External link opener hijack | `target="_blank"` always with `rel="noreferrer"` |

These sit on top of the negatives already recorded for M12.1–M12.5 (scope 404s, cross-client
A2A `TaskNotFound`, MCP origin refusal, non-forwarded exception text, and so on).

### Artifact download

`/api/v1/artifacts/:id/content` returns untrusted agent output. Served inline from the API
origin, an HTML artifact would run with the viewer's session. The response is forced to
download and sandboxed, the filename is reduced to `[a-zA-Z0-9._-]` so it cannot break the
header, and `Cache-Control: private, no-store` keeps it out of shared caches.

## Unknown-field compatibility

The rule on every surface: **unknown fields are ignored, never trusted, and never able to set
scope.**

| Surface | Behaviour |
| --- | --- |
| `POST /api/v1/runs` | Unknown body fields are ignored. `user_id` / `space_id` in the body are ignored; scope stays the signed identity and `X-Space-Id`. |
| MCP | Unknown `params` on a known method are ignored. |
| A2A | Unknown message, part and configuration fields are accepted (ProtoJSON forward compatibility); user and space still come from client config. |
| Browser SSE | `parseServerEvent` checks only the fields `applyEvent` reads. Extra fields pass through; an event missing a required field, or with the wrong type (e.g. `status: {"$gt": ""}`), is dropped with a warning instead of crashing the reducer or writing a malformed row into the cache. Event names outside the protocol are ignored. |

A dropped event still advances the client's SSE cursor, so a reconnect does not replay the
same malformed event forever.

## Not covered here

- No Content-Security-Policy on the SPA itself. Vega evaluates expressions at runtime, so a strict
  CSP needs testing against the chart views first. This is recorded as an M13.5 item.
- CSRF: the API authenticates with a bearer token in a header, never a cookie, so a cross-site
  form cannot carry credentials. Demo mode's `X-User-Id` is a custom header, which forces a CORS
  preflight that a foreign origin fails. Demo mode must still not be exposed publicly.
- The frontend client authenticates with `X-User-Id`, so the UI works only in `demo` mode
  (see `platform-api.md`).
