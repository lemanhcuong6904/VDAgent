# Runbook: startup order, readiness and graceful shutdown (M13.1)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

## Probes

| Endpoint | Meaning | Checks dependencies |
| --- | --- | --- |
| `GET /live` (alias `/health`) | Process is up and answering | No — a database outage must not restart every replica |
| `GET /ready` | Safe to route traffic | Yes: phase, `SELECT 1`, schema vs. this build |

`/ready` returns `503` with a reason in `checks`:

- `phase: starting|draining|stopped` — not accepting traffic yet or any more.
- `database: unreachable` — no connection; no error text is returned.
- `schema: pending` — this build knows migrations the database has not applied.
- `schema: ahead` — the database has migrations this build does not know (a newer image migrated,
  then this older one started). Do not route traffic: the older code may misread newer rows.
  Roll forward, or restore to a schema-compatible version.

## Startup order

1. Database healthy.
2. API starts and runs migrations under the advisory lock (`MIGRATION_LOCK_TIMEOUT_MS`, default
   120s). A replica that cannot get the lock in time **fails startup** with
   `MigrationLockTimeoutError` instead of hanging.
3. API becomes ready once the HTTP server listens.
4. Worker starts after the API is healthy (`depends_on: api: service_healthy`). It still takes the
   migration lock itself, so running it alone is safe.

## Shutdown (SIGTERM / SIGINT)

API, in order, bounded by `SHUTDOWN_TIMEOUT_MS` (30s):

1. Phase → `draining`; `/ready` answers 503 immediately.
2. Wait `SHUTDOWN_DRAIN_DELAY_MS` (5s) so the load balancer removes the replica.
3. `http`: stop accepting connections; after `HTTP_CLOSE_GRACE_MS` (5s) cut the rest. SSE clients
   reconnect elsewhere with their cursor and lose nothing.
4. `worker`: stop claiming; in-flight runs get `WORKER_DRAIN_GRACE_MS` (20s) to finish; the rest
   are handed back as `retryable` and re-claimed by another worker when their lease lapses.
5. `outbox`: stop publishing.
6. `database`: close the pool last.

A failed step does not skip later ones. Exit code 0 when every step succeeded, 1 otherwise or on
timeout. The process logs one `platform.shutdown` line with each step's result and duration.

The standalone worker runs steps 4–6 with no drain delay.

**Keep `stop_grace_period` (40s in compose) above `SHUTDOWN_TIMEOUT_MS`**, or the orchestrator
SIGKILLs mid-drain and runs wait a full lease before re-claim.

## Diagnosing

| Symptom | Check |
| --- | --- |
| Replica never becomes ready | `curl /ready` → `checks`. `pending` means migrations did not run; look for `MigrationLockTimeoutError` in startup logs and for a session holding lock `6041002` (`SELECT * FROM pg_locks WHERE locktype='advisory'`). |
| `schema: ahead` after a rollback | Expected; see above. |
| Shutdown exits 1 | Read the `platform.shutdown` line; the failing step is `ok:false`. |
| Runs stuck `running` after a deploy | The worker was SIGKILLed before drain; they re-claim after `WORKER_LEASE_MS`. See `stale-leases.md`. |
