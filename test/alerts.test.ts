/**
 * Alerts and Runbooks Tests - M11.6
 * Validates detection of stale leases, outbox lag, unknown events, cost, artifact mismatch and PII
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  type AlertSnapshot,
  AlertStore,
  evaluateAlerts,
  findPii,
  RUNBOOKS,
} from "../src/alerts.js";
import { migrateDatabase } from "../src/database.js";

const now = new Date(Date.UTC(2026, 8, 27, 12, 0, 0));

function snapshot(overrides: Partial<AlertSnapshot> = {}): AlertSnapshot {
  return {
    now,
    staleLeases: { overdueRuns: [], reclaimableRuns: 0 },
    outboxLag: { pending: 0, oldestPendingMs: null, exhausted: 0 },
    unknownEvents: [],
    cost: [],
    artifacts: { integrityFailures: [], failedPublications: 0 },
    pii: [],
    ...overrides,
  };
}

describe("Alert rules - M11.6", () => {
  it("stays silent on a healthy snapshot", () => {
    expect(evaluateAlerts(snapshot())).toEqual([]);
  });

  describe("stale leases", () => {
    it("warns past the lease deadline and escalates when long overdue", () => {
      const warning = evaluateAlerts(
        snapshot({
          staleLeases: {
            overdueRuns: [
              { runId: "run_1", status: "running", workerId: "worker-a", overdueMs: 90_000 },
            ],
            reclaimableRuns: 0,
          },
        }),
      );
      expect(warning).toHaveLength(1);
      expect(warning[0]).toMatchObject({
        signal: "stale_leases",
        severity: "warning",
        fingerprint: "stale_leases:warning",
        runbook: RUNBOOKS.stale_leases,
      });
      expect(warning[0].details).toMatchObject({ overdue: 1, worstOverdueMs: 90_000 });

      const critical = evaluateAlerts(
        snapshot({
          staleLeases: {
            overdueRuns: [
              { runId: "run_1", status: "leased", workerId: "worker-a", overdueMs: 400_000 },
            ],
            reclaimableRuns: 1,
          },
        }),
      );
      expect(critical[0]).toMatchObject({
        severity: "critical",
        fingerprint: "stale_leases:critical",
      });
      expect(critical[0].details).toMatchObject({ reclaimableRuns: 1 });
    });

    it("honours custom thresholds", () => {
      expect(
        evaluateAlerts(
          snapshot({
            staleLeases: {
              overdueRuns: [
                { runId: "run_1", status: "running", workerId: null, overdueMs: 5_000 },
              ],
              reclaimableRuns: 0,
            },
          }),
          { leaseOverdueWarningMs: 10_000 },
        ),
      ).toEqual([]);
    });
  });

  describe("outbox lag", () => {
    it("warns on lag or backlog and escalates for exhausted events", () => {
      const lagging = evaluateAlerts(
        snapshot({ outboxLag: { pending: 3, oldestPendingMs: 120_000, exhausted: 0 } }),
      );
      expect(lagging[0]).toMatchObject({ signal: "outbox_lag", severity: "warning" });

      const backlogged = evaluateAlerts(
        snapshot({ outboxLag: { pending: 2_000, oldestPendingMs: 1_000, exhausted: 0 } }),
      );
      expect(backlogged[0]).toMatchObject({ severity: "warning" });
      expect(backlogged[0].summary).toContain("2000 unpublished event(s)");

      const stalled = evaluateAlerts(
        snapshot({ outboxLag: { pending: 4, oldestPendingMs: 400_000, exhausted: 2 } }),
      );
      expect(stalled[0]).toMatchObject({
        severity: "critical",
        fingerprint: "outbox_lag:critical",
      });
      expect(stalled[0].summary).toContain("exhausted their publish attempts");
    });
  });

  describe("unknown events", () => {
    it("warns and reports the offending types", () => {
      const alerts = evaluateAlerts(
        snapshot({ unknownEvents: [{ eventType: "run.migrated", count: 4 }] }),
      );
      expect(alerts[0]).toMatchObject({ signal: "unknown_events", severity: "warning" });
      expect(alerts[0].details).toMatchObject({
        total: 4,
        types: [{ eventType: "run.migrated", count: 4 }],
      });
      expect(alerts[0].runbook).toBe(RUNBOOKS.unknown_events);
    });
  });

  describe("cost budget", () => {
    it("ignores spaces without a budget", () => {
      expect(
        evaluateAlerts(
          snapshot({ cost: [{ scopeKey: "ws_a", windowMs: 86_400_000, cost: 99, budget: null }] }),
        ),
      ).toEqual([]);
    });

    it("warns near the budget and escalates past it", () => {
      const warning = evaluateAlerts(
        snapshot({ cost: [{ scopeKey: "ws_a", windowMs: 86_400_000, cost: 85, budget: 100 }] }),
      );
      expect(warning[0]).toMatchObject({
        signal: "cost_budget",
        severity: "warning",
        fingerprint: "cost_budget:ws_a:warning",
      });

      const critical = evaluateAlerts(
        snapshot({ cost: [{ scopeKey: "ws_b", windowMs: 3_600_000, cost: 150, budget: 100 }] }),
      );
      expect(critical[0]).toMatchObject({
        severity: "critical",
        fingerprint: "cost_budget:ws_b:critical",
      });
      expect(critical[0].summary).toContain("150.0000 of 100.0000");
      expect(critical[0].summary).toContain("150% of budget");
    });
  });

  describe("artifact mismatch", () => {
    it("warns on failed publication and goes critical on a failed readback", () => {
      const warning = evaluateAlerts(
        snapshot({ artifacts: { integrityFailures: [], failedPublications: 2 } }),
      );
      expect(warning[0]).toMatchObject({
        signal: "artifact_mismatch",
        severity: "warning",
        fingerprint: "artifact_mismatch:warning",
      });

      const critical = evaluateAlerts(
        snapshot({
          artifacts: {
            integrityFailures: [{ artifactId: "dat_1", kind: "dataset" }],
            failedPublications: 0,
          },
        }),
      );
      expect(critical[0]).toMatchObject({ severity: "critical" });
      expect(critical[0].summary).toContain("hash or length readback");
    });
  });

  describe("PII leak", () => {
    it("is always critical and never carries a matched value", () => {
      const alerts = evaluateAlerts(
        snapshot({
          pii: [
            { finding: "email", source: "observability_logs", ref: "log:91" },
            { finding: "inline_secret", source: "audit_events", ref: "audit:12" },
          ],
        }),
      );
      expect(alerts[0]).toMatchObject({
        signal: "pii_leak",
        severity: "critical",
        runbook: RUNBOOKS.pii_leak,
      });
      expect(alerts[0].details).toMatchObject({
        findings: ["email", "inline_secret"],
        sources: ["observability_logs", "audit_events"],
      });
      expect(JSON.stringify(alerts)).not.toMatch(/@|hunter2/);
    });

    it("recognizes the PII shapes it claims to detect", () => {
      expect(findPii("mail alice@example.com")).toEqual(["email"]);
      expect(findPii("card 4111 1111 1111 1111")).toEqual(["payment_card"]);
      expect(findPii("token=abcd1234")).toEqual(["inline_secret"]);
      expect(findPii(`-----BEGIN RSA ${"PRIVATE"} KEY-----`)).toEqual(["private_key"]);
      expect(findPii("run run_42 completed in 1200ms")).toEqual([]);
    });
  });

  it("uses a fingerprint per firing condition so repeats do not duplicate", () => {
    const source = snapshot({
      staleLeases: {
        overdueRuns: [{ runId: "run_1", status: "running", workerId: "w", overdueMs: 90_000 }],
        reclaimableRuns: 0,
      },
      outboxLag: { pending: 2_000, oldestPendingMs: null, exhausted: 0 },
    });
    const first = evaluateAlerts(source).map((alert) => alert.fingerprint);
    const second = evaluateAlerts(source).map((alert) => alert.fingerprint);
    expect(first).toEqual(second);
    expect(new Set(first).size).toBe(first.length);
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("Alert store - M11.6 (PostgreSQL)", () => {
  let database: Pool;

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 4 });
    await migrateDatabase(database);
  });

  afterAll(async () => {
    await database?.end();
  });

  it("opens one row per condition, bumps occurrences and auto-resolves", async () => {
    const store = new AlertStore(database, {}, { piiScanLimit: 50, costWindowMs: 60_000 });
    const marker = `m11_6_${randomUUID()}`;
    const spaceId = `space_${randomUUID()}`;
    const runId = `run_${randomUUID()}`;

    // One overdue lease and one exhausted outbox event, both inside the scan window.
    await database.query(
      `INSERT INTO platform_runs (id, space_id, user_id, workflow_id, workflow_version, status,
        idempotency_key, worker_id, lease_until)
       VALUES ($1, $2, 'user_1', 'analytics', '1.0.0', 'running', $3, 'worker-a', now() - interval '10 minutes')`,
      [runId, spaceId, marker],
    );
    await database.query(
      `INSERT INTO platform_outbox_events (run_id, event_type, payload, attempts)
       VALUES ($1, 'run.status', '{}'::jsonb, 7)`,
      [runId],
    );

    try {
      const first = await store.run();
      const signals = first.map((alert) => alert.signal);
      expect(signals).toContain("stale_leases");
      expect(signals).toContain("outbox_lag");
      expect(first.find((alert) => alert.signal === "outbox_lag")?.severity).toBe("critical");

      await store.run();
      const open = await store.listOpen();
      const stale = open.filter((alert) => alert.signal === "stale_leases");
      expect(stale).toHaveLength(1);
      expect(stale[0].occurrences).toBe(2);
      expect(stale[0].firstSeenAt).not.toBe(stale[0].lastSeenAt);
      expect(stale[0].details).toMatchObject({ overdue: 1 });
    } finally {
      await database.query("DELETE FROM platform_outbox_events WHERE run_id = $1", [runId]);
      await database.query("DELETE FROM platform_runs WHERE id = $1", [runId]);
    }

    const after = await store.run();
    expect(after.map((alert) => alert.fingerprint)).not.toContain("stale_leases:warning");
    const resolved = await database.query<{ resolved_at: Date | null }>(
      `SELECT resolved_at FROM platform_alerts WHERE fingerprint = 'stale_leases:warning'`,
    );
    expect(resolved.rows.every((row) => row.resolved_at !== null)).toBe(true);
  });

  it("raises a PII alert from revealed log content without copying the value", async () => {
    const store = new AlertStore(database, {}, { piiScanLimit: 100 });
    const marker = `m11_6_pii_${randomUUID()}`;

    await database.query(
      `INSERT INTO observability_logs (timestamp, level, message, data)
       VALUES (now(), 'error', $1, '{}'::jsonb)`,
      [`${marker} leaked to alice@example.com`],
    );
    try {
      const alerts = await store.run();
      const pii = alerts.find((alert) => alert.signal === "pii_leak");
      expect(pii?.severity).toBe("critical");
      expect(JSON.stringify(pii)).not.toContain("alice@example.com");
      expect(pii?.details).toMatchObject({ findings: ["email"] });
    } finally {
      await database.query("DELETE FROM observability_logs WHERE message LIKE $1", [`${marker}%`]);
    }
  });
});
