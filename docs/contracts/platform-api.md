# Web API v1 — M12.1 / M12.2 / M12.3

**Status**: ✅ Completed (M12.1 endpoints, M12.2 semantics + legacy adapter, M12.3 UI run view)
**Module**: `src/platform-api.ts` (`registerPlatformApi`)
**Mounted**: `src/server.ts`, alongside the legacy `registerWebApi` projection

## Why a second surface exists

The legacy `/api/*` routes grew one feature at a time and now carry three different
conventions in one namespace: some return bare rows, some return a wrapper, and the report
and dataset routes return storage shapes with no stated contract. M12.1 adds a versioned
namespace with one consistent envelope so the UI can migrate route by route, and so a
breaking change has somewhere to happen that is not "the only API we have."

Both surfaces stay mounted during migration. **Rollback is deleting the single
`registerPlatformApi(...)` call in `src/server.ts`** — the legacy projection is unaffected either way,
because the new module shares no state with it.

## Scope resolution

Every route except `/api/v1/meta` runs through one gate:

1. `Authorization: Bearer <session>` is verified with `verifyWebSession`. In `session` mode a
   bare `X-User-Id` header is **not** accepted; in `demo` mode it still is, matching the
   existing `/api/*` behaviour.
2. The user must exist in `web_users`.
3. The space comes from `X-Space-Id`, falling back to `API_SPACE_ID`, then `local-space`.

The resolved `{userId, spaceId}` is the only scope a handler ever sees. A run, step, event,
evidence or artifact id that does not match the caller's scope returns `404` — not `403`,
so the API does not confirm that an out-of-scope id exists.

User ids and space ids are validated against `^[a-zA-Z0-9._:-]{1,128}$` before they reach a
query.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/meta` | Resource list, limits, cursor field. Unauthenticated. |
| `GET` | `/api/v1/registry/agents` | `AgentPool` projection — the registry actually in use. |
| `GET` | `/api/v1/registry/agents/:agentId` | Descriptor plus resolved `space_id`. |
| `GET` | `/api/v1/activation/agents` | Activation state per agent. |
| `POST` | `/api/v1/activation/agents/:agentId/:version` | `501` — see below. |
| `POST` | `/api/v1/plan/validate` | `PlanValidator.validate` over a posted plan. |
| `GET` | `/api/v1/runs` | Scoped list, `status` filter, clamped `limit`. |
| `POST` | `/api/v1/runs` | Queue a run; requires an idempotency key. |
| `GET` | `/api/v1/runs/:runId` | Run detail with `terminal` flag. |
| `POST` | `/api/v1/runs/:runId/cancel` | `409` when the run is unknown or already terminal. |
| `GET` | `/api/v1/runs/:runId/events` | Cursor replay over `platform_run_events`. |
| `GET` | `/api/v1/runs/:runId/stream` | SSE of the same log; resumes from `Last-Event-ID`. |
| `GET` | `/api/v1/legacy/tasks/:taskId/run` | Bridge a legacy task id to its run (M12.2). |
| `GET` | `/api/v1/runs/:runId/steps` | Step summaries; no bodies. |
| `GET` | `/api/v1/steps/:stepId` | Scoped through the parent run. |
| `GET` | `/api/v1/runs/:runId/checkpoints` | Projected from `evidence_refs.kind = 'checkpoint'`. |
| `GET` | `/api/v1/memory/:agentId` | Read-only memory inspection. |
| `GET` | `/api/v1/runs/:runId/evidence` | Evidence rows for a run. |
| `GET` | `/api/v1/evidence/:evidenceId` | One evidence row. |
| `GET` | `/api/v1/artifacts/:artifactId` | Artifact metadata. |
| `GET` | `/api/v1/artifacts/:artifactId/content` | Artifact bytes. |
| `GET` | `/api/v1/runs/:runId/receipt` | Newest terminal receipt. |
| `GET` | `/api/v1/runs/:runId/projection` | Observatory viewer projection (M11.5). |
| `GET` | `/api/v1/runs/:runId/view` | Composed UI view: graph, approvals, artifacts, evidence, cost, errors (M12.3). |

## What is deliberately absent

- **Activation mutation.** `src/registry/agent-registry.ts` holds activation state in memory
  and is wired to nothing but its own adapter, so activation is process configuration today.
  The `POST` route answers `501` with that reason rather than writing a state that no worker
  reads. `GET /activation/agents` projects the live `AgentPool` and says so in a `note` field.
- **Memory writes.** Memory is written through the `memory.remember` / `memory.forget` agent
  tools, which carry the tool-call scope and the approval path. v1 exposes inspection only.
- **Step bodies.** `platform_run_steps.input` and `output` are never serialized. The step DTO
  reports `has_input` / `has_output` booleans, and the viewer-facing content is the
  observatory projection and the evidence rows.

## Cursor replay

`GET /runs/:runId/events?after=<seq>` returns events with `seq > after`, ordered ascending,
and echoes the new `cursor`. A client that reconnects with the last cursor it applied
receives exactly the gap and no duplicates. `has_more` is true when the page filled.

- `after` omitted or empty means `0` (stream start).
- `after` that is not a non-negative safe integer is `422`, never a silent default.
- The limit is clamped to 200; the ledger itself clamps to 1000.

This is what satisfies the M12 PASS criterion "UI/API reconnect/replay không mất event": the
sequence number is durable in `platform_run_events` (`UNIQUE (run_id, seq)`), so the cursor
survives a server restart, not just a dropped connection.

## Idempotency

`POST /runs` requires a key of 1-256 characters, from `Idempotency-Key` or `idempotency_key`.

- First call: `202` with `replayed: false`.
- Same key, same request: `200` with `replayed: true`, the original run id and its current status.
- Same key, different request: `409 idempotency_conflict`; nothing is written.

The handler proposes its own run id and lets the ledger's
`ON CONFLICT (space_id, user_id, idempotency_key)` decide. If the returned id is not the
proposed one, an earlier request won, so detection needs no read-before-write and has no
race window. "Same request" is a canonical-JSON fingerprint of `workflow_id`,
`workflow_version` and `input`, compared against the stored run. Key order is ignored because
`jsonb` does not preserve it; array order and value types are not.

A replay is a success rather than a `409` because the caller's intent — "this run should
exist" — is satisfied. Reusing a key for a different intent is the conflict.

## Reconnect

`GET /runs/:runId/stream` is Server-Sent Events over the durable log. Each frame's `id` is the
event `seq`, so a browser `EventSource` reconnects with `Last-Event-ID` automatically and a
custom client can pass `after`. The stream pages through backlog at 200 events per read, then
polls (`streamPollMs`, default 1000). When the run is terminal and drained it sends
`event: stream.end` with the final cursor and closes.

The stream and `/events` read the same rows, so a client may mix them: page with `/events`,
then attach the stream at the returned cursor.

## Legacy adapter

`registerLegacyAdapter` is mounted **before** `registerWebApi` so its middleware wraps the old
routes. It never changes a legacy body or status. For routes with a v1 successor
(`/api/agents`, `/api/tasks/:id`, `/api/tasks/:id/cancel`, `/api/events`) it adds
`Deprecation: true` and `Link: <successor>; rel="successor-version"`. Routes without a
successor, such as `/api/users`, are left undecorated so the headers never point nowhere.

`/api/v1/legacy/tasks/:taskId/run` resolves `web_tasks.platform_run_id` for the owning user
and returns the run's event and stream URLs. A task created before migration 007 has no run id
and gets `404 run_missing` rather than a guess.

## UI run view (M12.3)

`GET /runs/:runId/view` is what the inspector's **Run** tab renders. It is built by the pure
`buildRunView` in `src/run-view.ts` from rows that were already loaded behind the scope gate,
and it re-checks the workspace on every row, not just the run:

- **Graph** and **errors** come from the observatory projection (M11.5), so event details are
  already stripped of raw prompt/tool content and error messages are capped.
- **Approvals** are the `approval`-kind steps, mapped to `pending` / `approved` / `rejected` /
  `cancelled`. `permissions.canDecideApproval` is always `false`: approval is decided by the
  host authority, and this surface has no route that could record a decision.
- **Artifacts** list the run's artifacts in the caller's workspace. `verified` is true only when
  the artifact is `ready` and a `verified` `artifact_ref` evidence row matches **both** its id
  and its sha256. An unverified or unavailable ref never counts, and neither does a verified
  ref from another workspace. Only a `ready` artifact gets a `contentUrl`.
- **Evidence** is counted by verification state and listed as content-free refs (tool id, model
  id, source location, checkpoint id), bounded at 200 with a `truncated` flag.
- **Cost** is the usage totals plus per-model and per-agent breakdowns.
- **Receipt** is the newest sealed terminal receipt in the caller's workspace, or `null`.
- **Permissions**: `canCancel` is true only for a non-terminal run with no pending cancel.

The UI claims success **only from a sealed receipt** (`outcomeLabel` in
`frontend/src/ui/runView.ts`). A `completed` run with no receipt shows "no receipt sealed yet",
which follows §15.4: a status field or a process exit is not proof.

`ArtifactStorage.listByOwnerRun(runId)` does not filter by workspace itself. A second tenant can
create an artifact with any `owner_run_id`, so the view drops rows whose `workspace_id` is not
the caller's. The PostgreSQL test sets up exactly this case and checks that the foreign
artifact's id does not appear anywhere in the response.

The frontend reaches the run through `/api/v1/legacy/tasks/:taskId/run`, so the existing task
list drives the new view without any change to legacy routes.

## Errors

One shape everywhere: `{"error": {"code": "...", "message": "..."}}`, including unknown
paths under `/api/v1/` (a catch-all registered last). Malformed JSON is `400`; well-formed JSON
of the wrong shape is `422`.

| Status | Codes |
| --- | --- |
| `400` | `invalid_json` |
| `401` | `authentication_required` |
| `404` | `not_found`, `receipt_missing`, `run_missing`, `route_not_found` |
| `409` | `not_cancellable`, `idempotency_conflict` |
| `422` | `invalid_plan`, `invalid_request`, `missing_idempotency_key`, `invalid_cursor` |
| `500` | `internal_error` |
| `501` | `not_supported` |
| `503` | `runner_disabled` |

## Type handling

`node-postgres` returns `bigint` and `numeric` as strings. Every DTO converts with `Number()`:
`attempt`, `max_attempts`, event `seq`, `duration_ms`, token counts. A client never has to
guess which numeric fields are quoted.

## Tests

```bash
npx vitest run test/platform-api.test.ts test/platform-api-replay.test.ts test/run-view.test.ts
(cd frontend && npm test)
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db \
  npx vitest run test/platform-api-replay.test.ts
```

`test/platform-api.test.ts` (24, no database) covers the security negatives: an unsigned caller
is rejected before any query, a session for an unknown user is rejected, the run list binds to
the signed identity rather than `X-User-Id`, `limit=100000` is clamped to 200, a step lookup
joins through its parent run, another user's run is `404`, a malformed cursor is `422`, step
bodies are never serialized, and an activation mutation is refused rather than faked.

`test/platform-api-replay.test.ts` (12) covers the adapter, the stream and the fingerprint with
mocks, and runs four tests against real PostgreSQL:

- five concurrent `POST /runs` with one key produce one run, one `202`, four `200`s and one
  `run.queued` event;
- a reused key with a different input is `409` and leaves exactly one row;
- a client reads the log, disconnects, misses two events, reconnects on the stream with
  `Last-Event-ID` while the run finishes, and ends up with every `seq` exactly once, in order;
- a valid session with a different `X-Space-Id` cannot stream the run.

The reconnect test was run five times consecutively without a failure.

## Known limits

- The run list has no cursor pagination yet; it trusts `limit` plus the `created_at DESC`
  ordering. Fine at current volume, a gap if a space accumulates runs in the tens of thousands.
- `workspace_id` in artifacts, evidence and receipts is bound to the caller's `space_id`. That
  is the tenancy key on `platform_runs`, so the binding is consistent, but the storage classes
  were written before this mapping existed and a future split of the two concepts would need a
  migration.
- The frontend client still authenticates with `X-User-Id`, which only works in `demo`
  auth mode. A deployment with `WEB_AUTH_MODE=session` needs the UI to send the signed session
  as a bearer token before the Run tab can load. This matches the existing `/api/*` UI.
- Artifact content is not linked from the UI yet, because a plain anchor cannot carry the
  auth header. The view returns `contentUrl` so a fetch-based download can be added later.
