# A2A gateway — M12.5 (optional)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed, **off by default**
**Module**: `src/a2a-gateway.ts` (`registerA2aGateway`), migration `017_a2a_tasks.sql`
**Protocol**: A2A 1.0, JSON-RPC binding (method and error tables of the 1.0 spec, ProtoJSON
per the normative `a2a.proto`: lowerCamelCase fields, enums as `TASK_STATE_*` / `ROLE_*`)

PLAN.md §8.4 lets an external A2A adapter exist only with auth/audience/tenant mapping, an Agent
Card version, task/artifact correlation, stream reconnect and a rate limit, and it must never
grant authority beyond internal policy. The gateway adds no SDK dependency. It maps A2A onto the
durable path that already exists, so every external task is a normal web task, invocation and
`web.agent_message` run, executed by the same worker.

## Enabling

| Variable | Meaning |
| --- | --- |
| `A2A_ENABLED=true` | Mount the routes. Anything else leaves them unmounted. |
| `A2A_CLIENTS` | JSON array of clients (below). Startup fails if empty or malformed. |
| `A2A_PUBLIC_URL` | Base URL placed in the Agent Card interface. |

```json
[{ "id": "partner-a", "tokenSha256": "<sha256 hex of the token>", "userId": "user_a",
   "spaceId": "space_a", "skills": ["analytics"], "rateLimit": 60 }]
```

Only the **hash** of each token is configured. A plaintext value in `tokenSha256` is refused at
startup. Enabling requires the durable run ledger (`PLATFORM_RUNNER_MODE` not `legacy`).

**Rollback:** unset `A2A_ENABLED`. Both routes disappear; `a2a_tasks` rows stay as an audit
record and their runs are ordinary runs.

## Routes

| Route | Auth |
| --- | --- |
| `GET /.well-known/agent-card.json` | Public |
| `POST /a2a` | Bearer token → client |

## Tenant mapping and authority

- The token selects a client. **User and space come from that client's config, never from the
  request.** An external caller has exactly the authority of its mapped user, no more.
- `skills` is the allowlist of agent ids the client may address. The skill is taken from
  `message.metadata.skillId`, or is the client's only skill. An ungranted skill and a missing
  one both return `Unknown skill`.
- The Agent Card advertises only skills some client is configured for. The rest of the internal
  registry is not visible.
- A task belonging to another client answers `TaskNotFoundError (-32001)`, the same as a task
  that does not exist, for both `GetTask` and `CancelTask`.
- Tokens are compared in constant time against every client, so response time does not show
  which client matched.

## Methods

| Method | Behaviour |
| --- | --- |
| `SendMessage` | Creates a task and returns `{task}` in `TASK_STATE_SUBMITTED`. Always returns immediately; the worker runs asynchronously. |
| `SendStreamingMessage` | Creates the task, then streams as `SubscribeToTask`. |
| `SubscribeToTask` | SSE of `StreamResponse`; the first frame is always the full `task`. |
| `GetTask` | The task. |
| `CancelTask` | Requests ledger cancellation; `-32002` if already terminal. |
| `ListTasks` | `-32004 UnsupportedOperationError` |
| Push notification config methods | `-32003 PushNotificationNotSupportedError` |
| `GetExtendedAgentCard` | `-32007 ExtendedAgentCardNotConfiguredError` |

Other codes: `-32700` parse error, `-32600` invalid envelope, `-32601` unknown method, `-32602`
invalid params, `-32603` internal error (with no detail), `-32005` for file (`url`/`raw`) parts,
`-32009` for an unsupported `A2A-Version`.

### Version

The spec says an absent or empty `A2A-Version` means 0.3. This gateway only speaks `1.0`, so a
request without the header gets `VersionNotSupportedError`. That is deliberate: silently
accepting a 0.3 client would mis-parse its `message/send` shapes.

## Messages

- `role` must be `ROLE_USER`. `text` parts are used as-is, `data` parts are JSON-encoded, and file
  parts are refused. Content is capped at 4,000 characters, the same as the web route.
- A message with `taskId` (continuing a task) is `UnsupportedOperationError`: there is no
  input-required continuation yet.
- **Idempotency:** `(client_id, messageId)` is unique. A retry with the same content returns the
  same task. A transaction-scoped advisory lock serializes concurrent retries, so they cannot
  create two tasks. A reused `messageId` with different content is refused.

## Task state

The invocation decides terminal state first, because the run can finish a moment before the
invocation records its reply:

| Source | State |
| --- | --- |
| invocation `completed` / `failed` / `cancelled` / `rejected` | `COMPLETED` / `FAILED` / `CANCELED` / `REJECTED` |
| run `cancelled` | `CANCELED` |
| run `queued` / `leased` | `SUBMITTED` |
| otherwise | `WORKING` |

A completed task carries the agent's reply as `status.message` and as one `reply` artifact. A
failed one carries the invocation's recorded error, never an exception string from the gateway.

## Streaming and reconnect

The stream polls the ledger (`streamPollMs`, default 1s) and emits `statusUpdate` on each state
change, with an `artifactUpdate` before the final status. It closes at a terminal state or after
`streamMaxMs` (default 10 minutes), after which the client resubscribes. Every frame is a
JSON-RPC response that carries the request id. Because the first frame of every subscription is
a full snapshot, a client that dropped mid-stream loses no outcome; it may miss intermediate
transitions, which A2A does not require it to see.

## Rate limit

Per client, over a 60-second window (`rateLimit`, default 60). Exceeding it gives `429` with
`Retry-After: 60`. The limiter is in-process, so N replicas allow N× the limit. A shared limiter
is an M13 item.

## Tests

```bash
npx vitest run test/a2a-gateway.test.ts
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db npx vitest run test/a2a-gateway.test.ts
```

24 tests, 6 of them on real PostgreSQL, run five times consecutively without a failure:

- a task lands on the durable path as `web.agent_message` under the client's mapped user and space;
- 4 concurrent sends of one `messageId` produce one task;
- a reused `messageId` with other content is refused;
- client B gets `TaskNotFound` for client A's task on both `GetTask` and `CancelTask`;
- a live task cancels once, and the second cancel is `TaskNotCancelable`;
- `SubscribeToTask` streams to `COMPLETED` with an artifact update, and a resubscribe after the
  drop returns the terminal snapshot with the reply.

The stream test sets the run and invocation to completed directly, as a stand-in for the worker.
It proves the gateway's projection and stream, not agent execution; agent execution is covered
by the existing durable-run tests.
