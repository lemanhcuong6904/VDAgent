/**
 * Alerts and runbooks - M11.6
 * Detects stale leases, outbox lag, unknown events, cost overrun, artifact mismatch and PII leaks.
 *
 * Evaluation is pure: `evaluateAlerts` maps a measurement snapshot to alert definitions, so rules
 * can be reviewed and tested without a database. `AlertStore` persists at most one open row per
 * firing condition and auto-resolves conditions that no longer fire. Alerts are advisory: they
 * never change run state and never authorize an action.
 */

import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import { REDACTED } from "./otel-observability.js";

export type AlertSignal =
  | "stale_leases"
  | "outbox_lag"
  | "unknown_events"
  | "cost_budget"
  | "artifact_mismatch"
  | "pii_leak";

export type AlertSeverity = "warning" | "critical";

export interface AlertDefinition {
  fingerprint: string;
  signal: AlertSignal;
  severity: AlertSeverity;
  title: string;
  /** Redacted, human-readable description; never contains a matched value. */
  summary: string;
  details: Record<string, unknown>;
  runbook: string;
}

export interface AlertRecord extends AlertDefinition {
  id: string;
  occurrences: number;
  firstSeenAt: string;
  lastSeenAt: string;
}

/** Raw measurements. Thresholds are applied by `evaluateAlerts`, not by the collector. */
export interface AlertSnapshot {
  now: Date;
  staleLeases: {
    overdueRuns: Array<{
      runId: string;
      status: string;
      workerId: string | null;
      overdueMs: number;
    }>;
    reclaimableRuns: number;
  };
  outboxLag: {
    pending: number;
    oldestPendingMs: number | null;
    exhausted: number;
  };
  unknownEvents: Array<{ eventType: string; count: number }>;
  cost: Array<{ scopeKey: string; windowMs: number; cost: number; budget: number | null }>;
  artifacts: {
    integrityFailures: Array<{ artifactId: string; kind: string }>;
    failedPublications: number;
  };
  pii: Array<{ finding: string; source: "observability_logs" | "audit_events"; ref: string }>;
}

export interface AlertThresholds {
  leaseOverdueWarningMs: number;
  leaseOverdueCriticalMs: number;
  outboxLagWarningMs: number;
  outboxLagCriticalMs: number;
  outboxPendingWarning: number;
  unknownEventWarning: number;
  costWarningRatio: number;
  costCriticalRatio: number;
  artifactFailureWarning: number;
}

export const DEFAULT_THRESHOLDS: AlertThresholds = {
  leaseOverdueWarningMs: 60_000,
  leaseOverdueCriticalMs: 300_000,
  outboxLagWarningMs: 60_000,
  outboxLagCriticalMs: 300_000,
  outboxPendingWarning: 1_000,
  unknownEventWarning: 1,
  costWarningRatio: 0.8,
  costCriticalRatio: 1,
  artifactFailureWarning: 1,
};

export const RUNBOOKS: Record<AlertSignal, string> = {
  stale_leases: "docs/runbooks/stale-leases.md",
  outbox_lag: "docs/runbooks/outbox-lag.md",
  unknown_events: "docs/runbooks/unknown-events.md",
  cost_budget: "docs/runbooks/cost-budget.md",
  artifact_mismatch: "docs/runbooks/artifact-mismatch.md",
  pii_leak: "docs/runbooks/pii-leak.md",
};

/** PII shapes worth alarming on: they never appear in a healthy run's logs or audit metadata. */
const PII_PATTERNS: ReadonlyArray<{ name: string; pattern: RegExp }> = [
  { name: "email", pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/ },
  { name: "payment_card", pattern: /\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b/ },
  { name: "us_ssn", pattern: /\b\d{3}-\d{2}-\d{4}\b/ },
  { name: "bearer_token", pattern: /Bearer\s+[A-Za-z0-9\-._~+/]{8,}=*/ },
  { name: "private_key", pattern: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  {
    name: "inline_secret",
    pattern: /\b(password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S{4,}/i,
  },
];

/**
 * Map a measurement snapshot to the alerts that should be open. Deterministic: same snapshot,
 * same fingerprints, so repeated evaluation never duplicates rows.
 */
export function evaluateAlerts(
  snapshot: AlertSnapshot,
  thresholds: Partial<AlertThresholds> = {},
): AlertDefinition[] {
  const limits = { ...DEFAULT_THRESHOLDS, ...thresholds };
  const alerts: AlertDefinition[] = [];

  const overdue = snapshot.staleLeases.overdueRuns.filter(
    (run) => run.overdueMs >= limits.leaseOverdueWarningMs,
  );
  if (overdue.length > 0) {
    const worst = overdue.reduce((max, run) => Math.max(max, run.overdueMs), 0);
    const critical = worst >= limits.leaseOverdueCriticalMs;
    alerts.push({
      fingerprint: critical ? "stale_leases:critical" : "stale_leases:warning",
      signal: "stale_leases",
      severity: critical ? "critical" : "warning",
      title: critical
        ? "Runner leases are long overdue"
        : "Runner leases are past their lease time",
      summary:
        `${overdue.length} leased run(s) passed their lease deadline; the longest is ` +
        `${Math.round(worst / 1000)}s overdue. Until a worker stops heartbeating or the lease ` +
        `is reclaimed, those runs hold their fencing token and no other worker can take them.`,
      details: {
        overdue: overdue.length,
        worstOverdueMs: worst,
        reclaimableRuns: snapshot.staleLeases.reclaimableRuns,
        sample: overdue
          .slice()
          .sort((left, right) => right.overdueMs - left.overdueMs)
          .slice(0, 5)
          .map((run) => ({ runId: run.runId, status: run.status, overdueMs: run.overdueMs })),
      },
      runbook: RUNBOOKS.stale_leases,
    });
  }

  const lag = snapshot.outboxLag.oldestPendingMs;
  const lagging = lag !== null && lag >= limits.outboxLagWarningMs;
  const backlogged = snapshot.outboxLag.pending >= limits.outboxPendingWarning;
  if (lagging || backlogged || snapshot.outboxLag.exhausted > 0) {
    const critical =
      (lag !== null && lag >= limits.outboxLagCriticalMs) || snapshot.outboxLag.exhausted > 0;
    const reasons = [
      lagging ? `${Math.round((lag as number) / 1000)}s since the oldest unpublished event` : null,
      backlogged ? `${snapshot.outboxLag.pending} unpublished event(s)` : null,
      snapshot.outboxLag.exhausted > 0
        ? `${snapshot.outboxLag.exhausted} event(s) exhausted their publish attempts`
        : null,
    ].filter((reason): reason is string => reason !== null);
    alerts.push({
      fingerprint: critical ? "outbox_lag:critical" : "outbox_lag:warning",
      signal: "outbox_lag",
      severity: critical ? "critical" : "warning",
      title: critical ? "Outbox delivery is stalled" : "Outbox delivery is lagging",
      summary:
        `Downstream consumers are behind: ${reasons.join("; ")}. Committed runs keep their ` +
        `journal, so this is a delivery delay rather than data loss.`,
      details: {
        pending: snapshot.outboxLag.pending,
        oldestPendingMs: lag,
        exhausted: snapshot.outboxLag.exhausted,
      },
      runbook: RUNBOOKS.outbox_lag,
    });
  }

  const unknownTotal = snapshot.unknownEvents.reduce((sum, event) => sum + event.count, 0);
  if (unknownTotal >= limits.unknownEventWarning) {
    alerts.push({
      fingerprint: "unknown_events",
      signal: "unknown_events",
      severity: "warning",
      title: "Runs emitted event types this deployment does not know",
      summary:
        `${unknownTotal} event(s) across ${snapshot.unknownEvents.length} unrecognized type(s). ` +
        `A newer producer is likely ahead of this build; older consumers must ignore unknown ` +
        `fields rather than fail the run.`,
      details: {
        total: unknownTotal,
        types: snapshot.unknownEvents.slice(0, 10),
      },
      runbook: RUNBOOKS.unknown_events,
    });
  }

  for (const entry of snapshot.cost) {
    if (entry.budget === null || entry.budget <= 0) continue;
    const ratio = entry.cost / entry.budget;
    if (ratio < limits.costWarningRatio) continue;
    const critical = ratio >= limits.costCriticalRatio;
    alerts.push({
      fingerprint: `cost_budget:${entry.scopeKey}:${critical ? "critical" : "warning"}`,
      signal: "cost_budget",
      severity: critical ? "critical" : "warning",
      title: critical ? "Spend passed its budget" : "Spend is close to its budget",
      summary:
        `${entry.scopeKey} spent ${entry.cost.toFixed(4)} of ${entry.budget.toFixed(4)} in the ` +
        `last ${Math.round(entry.windowMs / 3_600_000)}h (${Math.round(ratio * 100)}% of budget).`,
      details: {
        scope: entry.scopeKey,
        cost: entry.cost,
        budget: entry.budget,
        ratio: Number(ratio.toFixed(4)),
        windowMs: entry.windowMs,
      },
      runbook: RUNBOOKS.cost_budget,
    });
  }

  const integrity = snapshot.artifacts.integrityFailures;
  const failedPublications = snapshot.artifacts.failedPublications;
  if (integrity.length > 0 || failedPublications >= limits.artifactFailureWarning) {
    const critical = integrity.length > 0;
    alerts.push({
      fingerprint: critical ? "artifact_mismatch:critical" : "artifact_mismatch:warning",
      signal: "artifact_mismatch",
      severity: critical ? "critical" : "warning",
      title: critical
        ? "Published artifact content does not match its hash"
        : "Artifact publication failed",
      summary: critical
        ? `${integrity.length} ready artifact(s) failed a hash or length readback. Treat the ` +
          `stored content as untrusted until the source is republished.`
        : `${failedPublications} artifact(s) are stuck in a failed publication state.`,
      details: {
        integrityFailures: integrity.slice(0, 10),
        failedPublications,
      },
      runbook: RUNBOOKS.artifact_mismatch,
    });
  }

  if (snapshot.pii.length > 0) {
    const sources = [...new Set(snapshot.pii.map((item) => item.source))];
    alerts.push({
      fingerprint: "pii_leak",
      signal: "pii_leak",
      severity: "critical",
      title: "Personal data reached telemetry or the audit journal",
      summary:
        `${snapshot.pii.length} finding(s) of type ${[...new Set(snapshot.pii.map((item) => item.finding))].join(", ")} ` +
        `in ${sources.join(" and ")}. The matched values are never included in this alert; ` +
        `redaction is meant to stop this upstream.`,
      details: {
        findings: [...new Set(snapshot.pii.map((item) => item.finding))],
        sources,
        refs: snapshot.pii.slice(0, 10),
      },
      runbook: RUNBOOKS.pii_leak,
    });
  }

  return alerts;
}

/** Scan free text for PII shapes. Used for the observability and audit stores. */
export function findPii(text: string): string[] {
  const found: string[] = [];
  for (const { name, pattern } of PII_PATTERNS) {
    if (pattern.test(text)) found.push(name);
  }
  return [...new Set(found)];
}

export interface AlertStoreOptions {
  /** Recent events scanned for PII per evaluation. */
  piiScanLimit?: number;
  /** Spend window for the cost signal. */
  costWindowMs?: number;
}

/** Reads the ledger for alert measurements and persists the open set. */
export class AlertStore {
  private readonly piiScanLimit: number;
  private readonly costWindowMs: number;

  constructor(
    private readonly pool: Pool,
    private readonly thresholds: Partial<AlertThresholds> = {},
    options: AlertStoreOptions = {},
  ) {
    this.piiScanLimit = options.piiScanLimit ?? 500;
    this.costWindowMs = options.costWindowMs ?? 24 * 60 * 60 * 1_000;
  }

  async snapshot(now = new Date()): Promise<AlertSnapshot> {
    const [leases, outbox, events, cost, artifacts, pii] = await Promise.all([
      this.leaseMeasurements(now),
      this.outboxMeasurements(now),
      this.unknownEventMeasurements(),
      this.costMeasurements(),
      this.artifactMeasurements(),
      this.piiMeasurements(),
    ]);
    return {
      now,
      staleLeases: leases,
      outboxLag: outbox,
      unknownEvents: events,
      cost,
      artifacts,
      pii,
    };
  }

  /** Evaluate and persist. Returns the alerts that are now open. */
  async run(now = new Date()): Promise<AlertDefinition[]> {
    const alerts = evaluateAlerts(await this.snapshot(now), this.thresholds);
    await this.persist(alerts, now);
    return alerts;
  }

  async listOpen(): Promise<AlertRecord[]> {
    const result = await this.pool.query<AlertRow>(
      `SELECT id, fingerprint, signal, severity, title, summary, details, runbook,
              occurrences, first_seen_at, last_seen_at
       FROM platform_alerts WHERE resolved_at IS NULL ORDER BY last_seen_at DESC`,
    );
    return result.rows.map(toRecord);
  }

  /** Upsert the firing conditions and resolve any open alert that no longer fires. */
  private async persist(alerts: AlertDefinition[], now: Date): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const fingerprints = alerts.map((alert) => alert.fingerprint);
      await client.query(
        `UPDATE platform_alerts SET resolved_at = $2
         WHERE resolved_at IS NULL AND NOT (fingerprint = ANY($1::text[]))`,
        [fingerprints, now],
      );
      for (const alert of alerts) {
        await client.query(
          `INSERT INTO platform_alerts
             (fingerprint, signal, severity, title, summary, details, runbook, occurrences,
              first_seen_at, last_seen_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, 1, $8, $8)
           ON CONFLICT (fingerprint) WHERE resolved_at IS NULL
           DO UPDATE SET severity = EXCLUDED.severity, title = EXCLUDED.title,
                         summary = EXCLUDED.summary, details = EXCLUDED.details,
                         runbook = EXCLUDED.runbook,
                         occurrences = platform_alerts.occurrences + 1,
                         last_seen_at = EXCLUDED.last_seen_at`,
          [
            alert.fingerprint,
            alert.signal,
            alert.severity,
            alert.title,
            alert.summary,
            JSON.stringify({ ...alert.details, alertId: randomUUID() }),
            alert.runbook,
            now,
          ],
        );
      }
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  private async leaseMeasurements(now: Date): Promise<AlertSnapshot["staleLeases"]> {
    const result = await this.pool.query<{
      id: string;
      status: string;
      worker_id: string | null;
      overdue_ms: string;
    }>(
      `SELECT id, status, worker_id,
              (EXTRACT(EPOCH FROM ($1::timestamptz - lease_until)) * 1000)::bigint AS overdue_ms
       FROM platform_runs
       WHERE lease_until IS NOT NULL AND lease_until < $1 AND status IN ('leased', 'running')
       ORDER BY lease_until ASC LIMIT 50`,
      [now],
    );
    return {
      overdueRuns: result.rows.map((row) => ({
        runId: row.id,
        status: row.status,
        workerId: row.worker_id,
        overdueMs: Number(row.overdue_ms),
      })),
      reclaimableRuns: result.rows.filter((row) => row.status === "leased").length,
    };
  }

  private async outboxMeasurements(now: Date): Promise<AlertSnapshot["outboxLag"]> {
    const result = await this.pool.query<{
      pending: string;
      oldest_ms: string | null;
      exhausted: string;
    }>(
      `SELECT COUNT(*)::text AS pending,
              (EXTRACT(EPOCH FROM ($1::timestamptz - MIN(created_at))) * 1000)::bigint::text AS oldest_ms,
              COUNT(*) FILTER (WHERE attempts >= 5)::text AS exhausted
       FROM platform_outbox_events WHERE published_at IS NULL`,
      [now],
    );
    const row = result.rows[0];
    return {
      pending: Number(row?.pending ?? 0),
      oldestPendingMs:
        row?.oldest_ms === null || row?.oldest_ms === undefined ? null : Number(row.oldest_ms),
      exhausted: Number(row?.exhausted ?? 0),
    };
  }

  /** Event types seen recently that this build does not emit. */
  private async unknownEventMeasurements(): Promise<AlertSnapshot["unknownEvents"]> {
    const result = await this.pool.query<{ event_type: string; count: string }>(
      `SELECT event_type, COUNT(*)::text AS count
       FROM platform_run_events
       WHERE created_at > now() - interval '1 hour' AND NOT (event_type = ANY($1::text[]))
       GROUP BY event_type ORDER BY COUNT(*) DESC LIMIT 20`,
      [KNOWN_EVENT_TYPES],
    );
    return result.rows.map((row) => ({ eventType: row.event_type, count: Number(row.count) }));
  }

  private async costMeasurements(): Promise<AlertSnapshot["cost"]> {
    const result = await this.pool.query<{ space_id: string; cost: string }>(
      `SELECT space_id, COALESCE(SUM(estimated_cost), 0)::text AS cost
       FROM platform_usage_records
       WHERE created_at > now() - ($1::bigint / 1000) * interval '1 second'
       GROUP BY space_id`,
      [this.costWindowMs],
    );
    return result.rows.map((row) => ({
      scopeKey: row.space_id,
      windowMs: this.costWindowMs,
      cost: Number(row.cost),
      budget: parseBudget(
        process.env[`RUN_COST_BUDGET_${row.space_id}`] ?? process.env.RUN_COST_BUDGET,
      ),
    }));
  }

  private async artifactMeasurements(): Promise<AlertSnapshot["artifacts"]> {
    const [failed, integrity] = await Promise.all([
      this.pool.query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM artifacts WHERE status = 'failed'`,
      ),
      this.pool.query<{ id: string; kind: string }>(
        `SELECT id, kind FROM artifacts
         WHERE status = 'ready' AND (sha256 IS NULL OR bytes IS NULL OR length(sha256) <> 64)
         LIMIT 50`,
      ),
    ]);
    return {
      failedPublications: Number(failed.rows[0]?.count ?? 0),
      integrityFailures: integrity.rows.map((row) => ({ artifactId: row.id, kind: row.kind })),
    };
  }

  /** Recent logs and audit metadata scanned for PII shapes; matched values are discarded. */
  private async piiMeasurements(): Promise<AlertSnapshot["pii"]> {
    const [logs, audits] = await Promise.all([
      this.pool.query<{ id: string; message: string; data: unknown }>(
        `SELECT id::text AS id, message, data FROM observability_logs ORDER BY id DESC LIMIT $1`,
        [this.piiScanLimit],
      ),
      this.pool.query<{ id: string; action: string; metadata: unknown }>(
        `SELECT id::text AS id, action, metadata FROM platform_audit_events ORDER BY id DESC LIMIT $1`,
        [this.piiScanLimit],
      ),
    ]);

    const findings: AlertSnapshot["pii"] = [];
    for (const row of logs.rows) {
      const text = `${row.message} ${stringify(row.data)}`;
      for (const finding of findPii(text)) {
        findings.push({ finding, source: "observability_logs", ref: `log:${row.id}` });
      }
    }
    for (const row of audits.rows) {
      const text = `${row.action} ${stringify(row.metadata)}`;
      for (const finding of findPii(text)) {
        findings.push({ finding, source: "audit_events", ref: `audit:${row.id}` });
      }
    }
    return dedupeFindings(findings);
  }
}

const KNOWN_EVENT_TYPES = [
  "run.queued",
  "run.leased",
  "run.status",
  "run.cancel_requested",
  "step.queued",
  "step.started",
  "step.completed",
  "step.failed",
  "agent.message",
  "approval.requested",
  "approval.resolved",
  "artifact.published",
  "evidence.recorded",
  "receipt.sealed",
];

interface AlertRow {
  id: string;
  fingerprint: string;
  signal: AlertSignal;
  severity: AlertSeverity;
  title: string;
  summary: string;
  details: Record<string, unknown>;
  runbook: string;
  occurrences: number;
  first_seen_at: Date;
  last_seen_at: Date;
}

function toRecord(row: AlertRow): AlertRecord {
  return {
    id: String(row.id),
    fingerprint: row.fingerprint,
    signal: row.signal,
    severity: row.severity,
    title: row.title,
    summary: row.summary,
    details: row.details ?? {},
    runbook: row.runbook,
    occurrences: row.occurrences,
    firstSeenAt: new Date(row.first_seen_at).toISOString(),
    lastSeenAt: new Date(row.last_seen_at).toISOString(),
  };
}

function parseBudget(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function stringify(value: unknown): string {
  try {
    return typeof value === "string" ? value : JSON.stringify(value ?? "");
  } catch {
    return "";
  }
}

function dedupeFindings(findings: AlertSnapshot["pii"]): AlertSnapshot["pii"] {
  const seen = new Set<string>();
  return findings.filter((item) => {
    const key = `${item.finding}|${item.source}|${item.ref}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Marker used in tests and docs to prove alerts never carry a matched value. */
export const ALERT_REDACTION_MARKER = REDACTED;

/**
 * Periodic alert evaluation for the worker process. Runs never overlap; a failed evaluation is
 * reported and retried on the next tick instead of stopping the schedule.
 */
export class AlertScheduler {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private running: Promise<void> | undefined;
  private stopped = true;

  constructor(
    private readonly store: Pick<AlertStore, "run">,
    private readonly intervalMs: number,
    private readonly onError: (error: unknown) => void = () => undefined,
  ) {
    if (!Number.isSafeInteger(intervalMs) || intervalMs < 1_000)
      throw new Error("Alert interval must be at least 1000ms");
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.schedule(0);
  }

  /** Stops future ticks and waits for an in-flight evaluation to finish. */
  async stop(): Promise<void> {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    await this.running;
  }

  private schedule(delayMs: number): void {
    if (this.stopped) return;
    this.timer = setTimeout(() => {
      this.running = this.store
        .run()
        .then(() => undefined, this.onError)
        .finally(() => {
          this.running = undefined;
          this.schedule(this.intervalMs);
        });
    }, delayMs);
    this.timer.unref?.();
  }
}
