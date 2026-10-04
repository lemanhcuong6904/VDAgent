# Alerts and Runbooks - M11.6

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed
**Purpose**: Detect stale leases, outbox lag, unknown events, cost overrun, artifact mismatch and PII leaks

## Overview

`src/alerts.ts` evaluates the ledger for six operating conditions and persists one open row
per firing condition. Rules are pure: `evaluateAlerts(snapshot, thresholds)` maps a
measurement snapshot to alert definitions with no database involved, so a rule can be
reviewed and tested in isolation. `AlertStore` collects the snapshot from Postgres, evaluates
and persists. Every alert names the runbook that resolves it.

Alerts are advisory. They never change run state, never authorize an action, and never carry
a matched secret value.

## Signals

| Signal | Fires when | Default threshold | Runbook |
| --- | --- | --- | --- |
| `stale_leases` | A run is `leased`/`running` past `lease_until` | warning at 60s overdue, critical at 300s | [stale-leases](../runbooks/stale-leases.md) |
| `outbox_lag` | Unpublished outbox events accumulate | warning at 60s lag or 1000 pending, critical at 300s or any event with 5+ attempts | [outbox-lag](../runbooks/outbox-lag.md) |
| `unknown_events` | An event type outside `KNOWN_EVENT_TYPES` was written in the last hour | 1 event | [unknown-events](../runbooks/unknown-events.md) |
| `cost_budget` | Spend in the window against the space budget | warning at 80%, critical at 100% | [cost-budget](../runbooks/cost-budget.md) |
| `artifact_mismatch` | Failed publication, or a `ready` artifact with a missing or short SHA-256 | warning at 1 failed publication, critical on any readback failure | [artifact-mismatch](../runbooks/artifact-mismatch.md) |
| `pii_leak` | PII shapes found in recent `observability_logs` or `platform_audit_events` | always critical | [pii-leak](../runbooks/pii-leak.md) |

Thresholds are overridable per instance:

```typescript
new AlertStore(pool, { leaseOverdueWarningMs: 30_000, costWarningRatio: 0.9 });
```

Budgets come from `RUN_COST_BUDGET_<space_id>` or the shared `RUN_COST_BUDGET`. With neither
set the cost signal stays silent for that space.

## Lifecycle

```typescript
const store = new AlertStore(pool);
await store.run();        // evaluate + persist; safe to call on a timer
await store.listOpen();   // open alerts, newest first
```

- **Fingerprint** — one per firing condition, for example `stale_leases:critical` or
  `cost_budget:ws_a:warning`. Deterministic, so the same snapshot always yields the same set.
- **Deduplication** — a partial unique index on `fingerprint WHERE resolved_at IS NULL` means
  a repeat observation bumps `occurrences` and `last_seen_at` instead of inserting a row.
- **Auto-resolution** — conditions that stop firing are resolved in the same transaction that
  writes the current set. No manual closing is needed.

## Storage

`platform_alerts` (migration `016_platform_alerts`): `id`, `fingerprint`, `signal`, `severity`,
`title`, `summary`, `details` (jsonb), `runbook`, `occurrences`, `first_seen_at`,
`last_seen_at`, `resolved_at`. Indexes: partial unique on the open fingerprint, plus
`last_seen_at` and `(signal, severity)`.

## PII detection

`findPii(text)` recognizes emails, payment cards, US SSNs, bearer tokens, private keys and
inline `key=value` secrets. The store scans the newest rows of `observability_logs` and
`platform_audit_events` (500 each by default, configurable). Findings record the pattern name
and a row reference only; the matched value is discarded before the alert is built, so an
alert can never become a second copy of the leak.

## Reasoning behind the rules

- The lease and outbox signals warn before they escalate, because both are recoverable
  delays: the journal is committed, and a reclaim or a publisher restart drains them.
- `unknown_events` is a warning, not an error: an unrecognized type usually means a newer
  producer is running during a rolling deploy, and consumers are contractually expected to
  ignore unknown fields.
- Artifact readback failure is critical because evidence and receipts bind to the hash; a
  mismatch invalidates a published revision rather than delaying it.
- PII has no warning tier: once a value reaches a log or the audit journal it is already
  disclosed.

## Testing

```bash
# Unit tests (pure rules, no database)
npx vitest run test/alerts.test.ts

# Including the PostgreSQL store tests
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db npx vitest run test/alerts.test.ts
```

Coverage: each signal's thresholds and escalation, custom thresholds, budget opt-in,
fingerprint stability, the "healthy snapshot is silent" case, PII pattern recognition, and —
against Postgres — row deduplication with `occurrences` growth, auto-resolution, and a PII
alert raised from real log content that does not contain the matched address.
