# MCP server contract — M12.4

**Status**: ✅ Completed
**Module**: `src/mcp-server.ts` (`handleMcpRequest`), `src/mcp-run-reader.ts`
**Mounted**: `app.all("/mcp")` in `src/server.ts`
**Contract version**: `mcp-contract.v1` (server `0.2.0`)

The MCP endpoint lets an agent call its granted tools and read a small set of resources. It is
an external protocol surface, so the rule for M12 applies directly: **it must not open any
authority the agent does not already hold internally.** Every decision below comes back to that.

## Auth and audience

| Check | Where | Result on failure |
| --- | --- | --- |
| `X-Agent-Id` names a registered agent | `isAuthorizedAgent` | `401`, audited as `mcp_auth` denied |
| Bearer token equals `AGENT_TOKEN_<ID>` (constant-time) | `isAuthorizedAgent` | `401`, audited |
| `Origin`, when present, is in `MCP_ALLOWED_ORIGINS` | `handleMcpRequest` | `403` JSON-RPC error, before any handler runs |

The token's audience is one agent on this server: the token for `analytics` does not
authenticate as `visualize`, because the lookup key is derived from `X-Agent-Id` and compared in
constant time. User and space come from `API_USER_ID` / `API_SPACE_ID` on the server, never from
the request.

Agents call server-to-server and send no `Origin`. A browser always sends one. Refusing any
unlisted origin means a page in a user's browser cannot drive an agent's tools with a token the
browser might hold (DNS rebinding / CSRF). `MCP_ALLOWED_ORIGINS` is empty by default.

## Tools

`tools/list` returns the intersection of three grants: the tool's own `agents` list, the agent's
registered manifest, and the descriptor's `tools`. Removing a tool from any one of them hides it.
Mutating tools are annotated `destructiveHint: true`.

`tools/call` goes through `McpToolPool.call`, which re-checks all three grants, runs the tool's
own `authorize(scope)`, validates arguments against the schema **before** execution, and applies
the per-tool timeout. An object result is returned as both `text` and `structuredContent`.

### Error codes

Failures return `isError: true` with `structuredContent.error.code`:

| Code | Cause |
| --- | --- |
| `not_authorized` | Tool not granted, or `authorize()` refused the scope |
| `invalid_input` | Arguments do not match the input schema |
| `timeout` | Per-tool time limit exceeded |
| `cancelled` | Request aborted |
| `result_too_large` | Encoded result exceeds `max_result_bytes` |
| `tool_failed` | Anything else |

**Exception text is never forwarded.** Each code maps to a fixed message. A tool that throws
`connect ECONNREFUSED 10.0.0.7:5432 password=...` returns `tool_failed` and none of that
string; the test asserts this directly.

## Resources

| URI | Content |
| --- | --- |
| `platform://contract` | Contract and server version, supported protocol versions, auth scheme, scope, limits, visible tool names, error codes |
| `platform://agent/self` | The calling agent's own public descriptor, and no other agent's |
| `platform://runs/{runId}` | Observatory projection of a run (template; only when a run reader is configured) |

All resources carry `annotations.audience: ["assistant"]`.

A run is readable over MCP **only when the agent ran a step in it** and the run is in the
request's user and space (`ParticipatingRunReader`). Membership in the space is not enough,
because otherwise any agent token could read every run its tenant had ever made. The content is
the observatory projection, so step bodies and raw prompts are never included.

An out-of-scope run and a URI that does not exist return the **same** error, so an agent cannot
probe for run ids. Run ids must match `^[a-zA-Z0-9._:-]{1,128}$`; anything else, including path
traversal, never reaches the reader.

## Size

| Limit | Default | Setting |
| --- | --- | --- |
| Result or resource body | 256,000 bytes | `MCP_MAX_RESULT_BYTES` |
| Request body | 1,000,000 bytes | global `bodyLimit` in `src/server.ts` |
| Internal tool result | 1 MB | `McpToolPool.call` |

The limit is measured on the exact UTF-8 bytes that would be sent. An oversized result is
**refused, not truncated**: truncated JSON is either invalid or silently misleading, and an agent
acting on half a dataset is worse than one told to narrow its query.

## Versioning

`serverInfo.version` is the implementation version. `contract_version` in `platform://contract`
changes only on a breaking change to tool/resource shapes or error codes, and is also named in
the `instructions` string returned at initialize. The protocol version is negotiated by the SDK
from `SUPPORTED_PROTOCOL_VERSIONS`.

## Tests

```bash
npx vitest run test/mcp-server.test.ts
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db npx vitest run test/mcp-server.test.ts
```

23 tests, driven over real JSON-RPC through the SDK transport with a real `McpToolPool`. The 3
PostgreSQL tests show that a participating agent reads the run without step bodies, an agent in
the same space that took no part is refused, and the participating agent under another user or
space is refused.

## Rollback

Remove `descriptor`, `runs` and `allowedOrigins` from the `handleMcpRequest` call to go back to
tools-only behaviour. Removing `runs` alone also removes the run template from
`resources/templates/list`.
