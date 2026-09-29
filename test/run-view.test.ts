/**
 * Run View Tests - M12.3
 * The view is what the UI renders, so the tests pin what it must never show:
 * rows from another workspace, an unverified artifact labelled verified, or a
 * control the viewer is not allowed to use.
 */

import { Hono } from "hono";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { ArtifactMetadata } from "../src/artifact-storage.js";
import type { Evidence } from "../src/evidence-storage.js";
import type { ObservatoryProjection } from "../src/observatory.js";
import { registerPlatformApi } from "../src/platform-api.js";
import { AgentPool } from "../src/registry.js";
import { buildRunView, MAX_VIEW_EVIDENCE } from "../src/run-view.js";
import type { TerminalReceipt } from "../src/terminal-receipt-storage.js";
import { issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

const totals = { records: 1, inputTokens: 10, outputTokens: 5, latencyMs: 20, estimatedCost: 0.25 };

function projection(overrides: Partial<ObservatoryProjection["run"]> = {}): ObservatoryProjection {
  return {
    run: {
      id: "run_1",
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      status: "running",
      createdAt: "2026-09-27T12:00:00.000Z",
      updatedAt: "2026-09-27T12:00:01.000Z",
      finishedAt: null,
      durationMs: null,
      ...overrides,
    },
    timeline: [],
    graph: {
      nodes: [
        {
          id: "step_plan",
          kind: "planner",
          agentId: null,
          capability: null,
          status: "completed",
          attempt: 0,
          startedAt: "2026-09-27T12:00:00.000Z",
          finishedAt: "2026-09-27T12:00:01.000Z",
          durationMs: 1000,
        },
        {
          id: "step_gate",
          kind: "approval",
          agentId: null,
          capability: "publish",
          status: "waiting",
          attempt: 0,
          startedAt: "2026-09-27T12:00:01.000Z",
          finishedAt: null,
          durationMs: null,
        },
        {
          id: "step_gate_2",
          kind: "approval",
          agentId: null,
          capability: "delete",
          status: "failed",
          attempt: 0,
          startedAt: "2026-09-27T12:00:01.000Z",
          finishedAt: "2026-09-27T12:00:03.000Z",
          durationMs: 2000,
        },
      ],
      edges: [{ from: "step_plan", to: "step_gate" }],
      roots: ["step_plan"],
    },
    usage: { totals, byKind: {}, byModel: { "model-a": totals }, byAgent: { analytics: totals } },
    wait: { queuedMs: 0, waitingMs: 0, intervals: [], waitingSteps: [] },
    errors: [
      {
        source: "step",
        ref: "step_gate_2",
        message: "rejected by policy",
        at: "2026-09-27T12:00:03.000Z",
      },
    ],
    recovery: {
      attempts: 0,
      maxAttempts: 1,
      leases: 1,
      retries: 0,
      workers: [],
      cancelRequested: false,
      recovered: false,
    },
    truncated: false,
  };
}

const at = new Date("2026-09-27T12:00:02.000Z");

function artifact(overrides: Partial<ArtifactMetadata>): ArtifactMetadata {
  return {
    id: "dat_1",
    workspaceId: "space_a",
    ownerRunId: "run_1",
    kind: "dataset",
    version: "1",
    status: "ready",
    sha256: "aaa",
    bytes: 12,
    metadata: {},
    createdAt: at,
    readyAt: at,
    ...overrides,
  };
}

function artifactRef(
  artifactId: string,
  sha: string,
  verification: Evidence["verification"],
  workspaceId = "space_a",
): Evidence {
  return {
    id: `ev_${artifactId}_${verification}`,
    workspaceId,
    runId: "run_1",
    attemptId: "att_1",
    kind: "artifact_ref",
    verification,
    metadata: {},
    createdAt: at,
    verifiedAt: verification === "verified" ? at : null,
    artifactId,
    artifactSha256: sha,
  };
}

function view(input: Partial<Parameters<typeof buildRunView>[0]> = {}) {
  return buildRunView({
    projection: projection(),
    cancelRequested: false,
    evidence: [],
    artifacts: [],
    receipt: null,
    spaceId: "space_a",
    apiPrefix: "/api/v1",
    ...input,
  });
}

describe("run view - workspace isolation", () => {
  it("drops evidence, artifacts and receipts from another workspace", () => {
    const foreignReceipt = {
      id: "rcpt_x",
      workspaceId: "space_b",
      runId: "run_1",
      attemptId: "att_1",
      status: "success",
      exitCode: 0,
      inputHash: "h",
      outputHash: "h",
      artifactIds: [],
      evidenceCount: 1,
      verifiedEvidenceCount: 1,
      durationMs: 10,
      tokensInput: null,
      tokensOutput: null,
      sealedAt: at,
      metadata: {},
    } satisfies TerminalReceipt;
    const result = view({
      evidence: [artifactRef("dat_1", "aaa", "verified", "space_b")],
      artifacts: [artifact({ workspaceId: "space_b" })],
      receipt: foreignReceipt,
    });
    expect(result.evidence.items).toEqual([]);
    expect(result.artifacts).toEqual([]);
    expect(result.receipt).toBeNull();
  });

  it("does not let foreign evidence verify a local artifact", () => {
    const result = view({
      evidence: [artifactRef("dat_1", "aaa", "verified", "space_b")],
      artifacts: [artifact({})],
    });
    expect(result.artifacts[0].verified).toBe(false);
  });
});

describe("run view - artifact verification", () => {
  it("marks verified only when a verified ref matches id and hash", () => {
    const result = view({
      evidence: [
        artifactRef("dat_1", "aaa", "verified"),
        artifactRef("dat_2", "stale", "verified"),
      ],
      artifacts: [artifact({}), artifact({ id: "dat_2", sha256: "bbb" })],
    });
    expect(result.artifacts.map((row) => [row.id, row.verified])).toEqual([
      ["dat_1", true],
      ["dat_2", false],
    ]);
  });

  it("never treats an unverified or unavailable ref as verification", () => {
    const result = view({
      evidence: [
        artifactRef("dat_1", "aaa", "unverified"),
        artifactRef("dat_1", "aaa", "unavailable"),
      ],
      artifacts: [artifact({})],
    });
    expect(result.artifacts[0].verified).toBe(false);
    expect(result.evidence.counts).toEqual({ verified: 0, unverified: 1, unavailable: 1 });
  });

  it("offers no content link for a pending or failed artifact", () => {
    const result = view({
      artifacts: [
        artifact({ id: "dat_p", status: "pending" }),
        artifact({ id: "dat_f", status: "failed" }),
        artifact({}),
      ],
    });
    expect(result.artifacts.map((row) => row.contentUrl)).toEqual([
      null,
      null,
      "/api/v1/artifacts/dat_1/content",
    ]);
  });
});

describe("run view - approvals, cost and permissions", () => {
  it("maps approval steps to a decision state", () => {
    const result = view();
    expect(result.approvals).toEqual([
      {
        stepId: "step_gate",
        state: "pending",
        requestedAt: "2026-09-27T12:00:01.000Z",
        decidedAt: null,
        waitedMs: null,
      },
      {
        stepId: "step_gate_2",
        state: "rejected",
        requestedAt: "2026-09-27T12:00:01.000Z",
        decidedAt: "2026-09-27T12:00:03.000Z",
        waitedMs: 2000,
      },
    ]);
  });

  it("carries cost by model and agent from the projection", () => {
    const result = view();
    expect(result.cost.totals.estimatedCost).toBe(0.25);
    expect(Object.keys(result.cost.byModel)).toEqual(["model-a"]);
  });

  it("allows cancel only on a live run not already cancelling", () => {
    expect(view().permissions.canCancel).toBe(true);
    expect(view({ cancelRequested: true }).permissions.canCancel).toBe(false);
    expect(view({ projection: projection({ status: "completed" }) }).permissions.canCancel).toBe(
      false,
    );
  });

  it("never grants an approval decision from this surface", () => {
    expect(view().permissions.canDecideApproval).toBe(false);
  });

  it("bounds the evidence list and flags truncation", () => {
    const many = Array.from({ length: MAX_VIEW_EVIDENCE + 5 }, (_, index) =>
      artifactRef(`dat_${index}`, "x", "unverified"),
    );
    const result = view({ evidence: many });
    expect(result.evidence.items).toHaveLength(MAX_VIEW_EVIDENCE);
    expect(result.evidence.truncated).toBe(true);
    expect(result.evidence.counts.unverified).toBe(MAX_VIEW_EVIDENCE + 5);
  });

  it("keeps evidence refs free of payload content", () => {
    const text = JSON.stringify(
      view({ evidence: [artifactRef("dat_1", "aaa", "verified")] }).evidence,
    );
    expect(text).not.toMatch(/metadata|"input"|"output"/);
  });
});

describe("run view endpoint", () => {
  const webAuth: WebAuthConfig = {
    mode: "session",
    secret: "local-run-view-signing-key-only",
    ttlSeconds: 60,
  };

  it("returns 404 without loading evidence when the run is out of scope", async () => {
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM web_users WHERE id")) return { rows: [{ id: "owner" }] };
      return { rows: [] };
    });
    const app = new Hono();
    registerPlatformApi(app, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
      webAuth,
      spaceId: "local-space",
    });
    const response = await app.request("/api/v1/runs/run_other/view", {
      headers: { Authorization: `Bearer ${issueWebSession("owner", webAuth)}` },
    });
    expect(response.status).toBe(404);
    const touched = query.mock.calls.map(([sql]) => String(sql)).join("\n");
    expect(touched).not.toContain("evidence_refs");
    expect(touched).not.toContain("FROM artifacts");
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("run view endpoint - M12.3 (PostgreSQL)", () => {
  const webAuth: WebAuthConfig = {
    mode: "session",
    secret: "local-run-view-db-signing-key-only",
    ttlSeconds: 60,
  };
  let database: import("pg").Pool;
  const suffix = Math.random().toString(36).slice(2, 10);
  const userId = `user_${suffix}`;
  const spaceId = `space_${suffix}`;
  const runId = `run_view_${suffix}`;

  beforeAll(async () => {
    const { Pool } = await import("pg");
    const { migrateDatabase } = await import("../src/database.js");
    database = new Pool({ connectionString: databaseUrl, max: 4 });
    await migrateDatabase(database);
    await database.query(
      "INSERT INTO web_users (id, name) VALUES ($1, $1) ON CONFLICT DO NOTHING",
      [userId],
    );
    await database.query(
      `INSERT INTO platform_runs (id, space_id, user_id, workflow_id, workflow_version, status, idempotency_key, finished_at)
       VALUES ($1, $2, $3, 'analytics', '1.0.0', 'completed', $1, now())`,
      [runId, spaceId, userId],
    );
  });

  afterAll(async () => {
    await database?.query("DELETE FROM evidence_refs WHERE run_id = $1", [runId]);
    await database?.query(
      "DELETE FROM artifact_contents WHERE artifact_id IN (SELECT id FROM artifacts WHERE owner_run_id = $1)",
      [runId],
    );
    await database?.query("DELETE FROM artifacts WHERE owner_run_id = $1", [runId]);
    await database?.query("DELETE FROM platform_runs WHERE id = $1", [runId]);
    await database?.query("DELETE FROM web_users WHERE id = $1", [userId]);
    await database?.end();
  });

  it("composes real rows and excludes an artifact another workspace hung on the same run id", async () => {
    const { ArtifactStorage } = await import("../src/artifact-storage.js");
    const { EvidenceStorage } = await import("../src/evidence-storage.js");
    const artifacts = new ArtifactStorage(database);
    const evidence = new EvidenceStorage(database);

    const mine = await artifacts.store({
      workspaceId: spaceId,
      ownerRunId: runId,
      kind: "dataset",
      version: "1",
      content: Buffer.from("rows"),
    });
    const foreign = await artifacts.store({
      workspaceId: "someone-else",
      ownerRunId: runId,
      kind: "dataset",
      version: "1",
      content: Buffer.from("secret rows"),
    });
    const ref = await evidence.recordArtifactRef({
      workspaceId: spaceId,
      runId,
      attemptId: "att_1",
      artifactId: mine.id,
      artifactSha256: mine.sha256,
    });
    await evidence.markVerified(ref, spaceId);

    const app = new Hono();
    registerPlatformApi(app, {
      database,
      pluginRegistry: new AgentPool(),
      webAuth,
      spaceId,
    });
    const response = await app.request(`/api/v1/runs/${runId}/view`, {
      headers: {
        Authorization: `Bearer ${issueWebSession(userId, webAuth)}`,
        "X-Space-Id": spaceId,
      },
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as {
      run: { terminal: boolean };
      artifacts: { id: string; verified: boolean }[];
      evidence: { counts: { verified: number } };
      receipt: unknown;
      permissions: { canCancel: boolean };
    };
    expect(body.artifacts.map((row) => row.id)).toEqual([mine.id]);
    expect(body.artifacts[0].verified).toBe(true);
    expect(JSON.stringify(body)).not.toContain(foreign.id);
    expect(body.evidence.counts.verified).toBe(1);
    expect(body.run.terminal).toBe(true);
    expect(body.receipt).toBeNull();
    expect(body.permissions.canCancel).toBe(false);
  });
});
