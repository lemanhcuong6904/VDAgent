# Production authentication design (WS7 F-05)

Status: **BLOCKED: needs a decision.** This is a design only. Nothing here is implemented, and no identity provider
(IdP) has been chosen or configured. The offline demo keeps its current behaviour. It must not be deployed to any
network other than a developer machine.

## 1. Current state (verified)

- **REST and SSE.** `backend/vdagent_backend/http/deps.py` `current_user` trusts the `X-User-Id` header. The only check
  is that the id exists in `users`. Any client can impersonate any user.
- **Frontend.** `frontend/src/api/client.ts` sends `X-User-Id` for the user chosen in the sidebar `<select>`.
- **MCP (agent to backend).** Access uses per-invocation bearer tokens (`tokens.py`, `McpIdentity`). The backend
  issues them itself and revokes them when the turn closes. These tokens are already bound to (user, agent,
  invocation, task) and are **out of scope** for this finding.
- **Data authorization.** Per-user scopes (`db/scopes.py`, e.g. Alice → PRJ-X, Bob → PRJ-Y) are enforced downstream of
  the user id. They stay correct *only if* the user id is authentic.

## 2. Requirements

1. Authenticate the user identity cryptographically. No client-asserted identifiers.
2. Map a verified identity to exactly one `users.id`. Unknown identities are rejected, not auto-created, unless an
   owner approves just-in-time provisioning.
3. Keep project-scope authorization in the backend (`scopes.py`). The IdP asserts *who* the user is, never *which data*
   they may see, unless an owner approves group-to-scope mapping.
4. Protect SSE (`/api/events`) the same way as REST.
5. Run offline tests and the demo without an IdP. The header mode stays available **only** behind an explicit
   dev flag that refuses to start on a non-loopback bind.
6. Never log tokens, and never return them in errors.

## 3. Proposed design (IdP-agnostic)

- **Pluggable `Authenticator`** in `api/deps.py`, selected by config `auth.mode`:
  - `dev_header`: today's behaviour. It is allowed only when the bind address is loopback and
    `VDAGENT_ALLOW_DEV_AUTH=1`. Otherwise startup fails.
  - `oidc`: validates an `Authorization: Bearer <JWT>` access token.
    - Validation: signature via the IdP's JWKS (cached, with key rotation), `iss`, `aud`, `exp`/`nbf`, and an
      allow-listed `alg` (no `none`, no HS* with a public key).
    - Identity: the configured subject claim (default `sub`) maps to `users.external_subject`. A new column with a
      unique index is required.
- **SSE.** Browsers cannot set headers on `EventSource`. Two options: exchange the token for a short-lived,
  single-use stream ticket (`POST /api/events/ticket`, TTL ≤ 60 s, bound to the user), or switch to
  fetch-based SSE with an `Authorization` header.
- **Frontend.** Standard OIDC Authorization Code + PKCE, with the library chosen together with the IdP. Tokens are
  held in memory, with a silent refresh. Remove the user `<select>` in `oidc` mode.
- **Audit.** Record the authenticated subject on `tasks` and `reports` creation (the user id already exists; add
  `auth_subject`).
- **Tests.**
  - Positive and negative JWT cases: bad signature, wrong `iss`/`aud`, expired, `alg=none`, unknown subject.
  - A key-rotation test.
  - Dev-mode refusal on a non-loopback bind.
  - Cross-user isolation re-run with real tokens.
  - All of these run against a local test issuer (a JWKS the test generates), not a real IdP.

## 4. Decisions required (owner)

| # | Decision | Options | Blocking |
|---|---|---|---|
| AUTH-1 | Which IdP / issuer | The organisation's existing OIDC provider (name, issuer URL, audience) | Implementation |
| AUTH-2 | Subject claim and user provisioning | `sub` vs `email`/`preferred_username`; pre-provisioned only vs just-in-time | Migration |
| AUTH-3 | Where project scopes come from | Backend table (current) vs IdP groups (needs a mapping approval) | Scope model |
| AUTH-4 | SSE authentication | Stream ticket vs fetch-SSE | Frontend work |
| AUTH-5 | Deployment boundary | Backend behind an authenticating reverse proxy (then trust only the proxy's signed header) vs in-app validation | Architecture |

Until AUTH-1…AUTH-5 are decided, **the system is not production-ready**. The offline demo (`dev_header`) is the
only supported mode.
