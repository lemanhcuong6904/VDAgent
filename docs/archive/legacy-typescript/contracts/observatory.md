# Observatory Projection - M11.5

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed
**Purpose**: Read-only run view: timeline, graph, usage, wait, error, recovery; no raw prompt

## Overview

`src/observatory.ts` projects one run from the canonical ledger into a viewer-facing read
model. It is strictly derived: rows come from `platform_runs`, `platform_run_steps`,
`platform_run_events` and `platform_usage_records`, and nothing is written back. The live
view is a projection; the ledger stays canonical, so disabling the projection loses no
state and authorizes nothing.

The projector never selects the `input` or `output` columns of runs or steps, and every
event payload is sanitized before it is returned. Raw prompts and model payloads cannot
reach a viewer.

## API

```typescript
const projector = new ObservatoryProjector(pool);

const projection = await projector.get(runId, { spaceId, userId });
if (!projection) return notFound();   // unknown run, or outside the caller's scope
```

```typescript
// Pure builder, for tests and for callers that already hold the rows
const projection = buildObservatoryProjection({ run, steps, events, usage }, { now });
```

## Projection shape

| Section | Contents |
| --- | --- |
| `run` | id, workflow id/version, status, timestamps, duration when finished |
| `timeline` | Events ordered by `seq`: type, timestamp, sanitized detail (internal `seq` removed) |
| `graph` | Step nodes (kind, agent, capability, status, attempt, start/finish, duration), parent edges, roots |
| `usage` | Token, latency and cost totals overall and grouped by kind, model (`provider/model`) and agent |
| `wait` | `queuedMs` (creation to first lease), `waitingMs`, the waiting intervals, and the steps still waiting |
| `errors` | Every available error with its source (`event`, `step`, `run`) and reference |
| `recovery` | Attempts, max attempts, lease count, retry count, worker ids, cancel flag, `recovered` |
| `truncated` | `true` when the event list hit the load limit (1000) and the timeline is partial |

An open waiting interval is measured up to the caller's `now`; closed ones end at the event
that left `waiting`. `recovered` is true only when the run retried at least once and still
reached `completed`.

## No raw prompt

Event detail sanitization, applied at any depth up to 4:

- **Raw content keys are dropped entirely**: `input`, `output`, `content`, `message`,
  `messages`, `text`, `body`, `arguments`, `result`, `response`, `completion`.
- **Sensitive keys** (`prompt`, `password`, `token`, `api_key`, `authorization`, …) become
  `[REDACTED]`, matching the M11.4 key list in `src/otel-observability.ts`.
- **Value patterns** (inline secrets, Bearer tokens, emails, cards, SSNs, long opaque
  tokens) are redacted in every string.
- Strings truncate at 200 characters and errors at 500.

## Authorization

`ObservatoryProjector.get` filters on `space_id` **and** `user_id`; a run outside the caller's
scope returns `null`, the same answer as a run that does not exist. No separate permission
check is needed because the projection only reads rows the caller already owns.

## Relationship to M11.4

The redaction helpers (`isSensitiveKey`, `redactText`, `REDACTED`) are exported from
`src/otel-observability.ts` and shared, so telemetry and projection redact identically.
Telemetry in M11.4 never authorizes an action; this projection is equally read-only, and the
canonical answer to "did this run succeed" remains the terminal receipt (M11.3).

## Not yet exposed

No HTTP route or UI surface serves the projection yet — that is M12.1/M12.3. Today it is a
library used by tests and available to the API layer.

## Testing

```bash
# Unit tests (pure builder, no database): 13 tests
npx vitest run test/observatory.test.ts

# Including the PostgreSQL projection test
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db npx vitest run test/observatory.test.ts
```

The PostgreSQL test drives a real run through `RunLedger` (create, claim, transition,
usage), writes a step whose `input` and `output` hold a prompt marker, then asserts the
projection contains the timeline, graph, usage and queue time while the serialized
projection never contains the marker — and that another user id gets `null`.
