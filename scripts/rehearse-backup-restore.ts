/**
 * M13.2 backup/restore rehearsal.
 *
 *   seed    <url>                  write a known state into a disposable database
 *   verify  <url> <state.json>     check a restored copy against that state, then run
 *                                  the recovery paths (lease re-claim, outbox, idempotent
 *                                  replay, receipt replay) against the restore
 *
 * Driven by scripts/rehearse-backup-restore.sh, which does the pg_dump/pg_restore in
 * between. Refuses to run unless the URL names a database containing "rehearsal".
 */

import { createHash, randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { Pool } from "pg";
import { ArtifactStorage } from "../src/artifact-storage.js";
import { migrateDatabase, migrationStatus } from "../src/database.js";
import { OutboxPublisher } from "../src/outbox.js";
import { RunLedger } from "../src/run-ledger.js";
import { TerminalReceiptStorage } from "../src/terminal-receipt-storage.js";

const COUNTED_TABLES = [
  "platform_runs",
  "platform_run_events",
  "platform_outbox_events",
  "platform_idempotency_keys",
  "artifacts",
  "artifact_contents",
  "terminal_receipts",
  "pi_sessions",
  "agent_memory_entries",
  "schema_migrations",
] as const;

type State = {
  seededAt: string;
  space: string;
  user: string;
  counts: Record<string, number>;
  artifacts: Array<{ id: string; sha256: string; bytes: number }>;
  staleRunId: string;
  queuedRunId: string;
  idempotencyKey: string;
  pendingOutbox: number;
  receiptInput: unknown;
  receiptId: string;
  sessionDigest: string;
  maxEventSeq: Record<string, number>;
};

const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

function guard(url: string): void {
  const name = new URL(url).pathname.slice(1);
  if (!name.includes("rehearsal"))
    throw new Error(`Refusing to touch database '${name}': name must contain "rehearsal"`);
}

async function counts(pool: Pool): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  for (const table of COUNTED_TABLES) {
    out[table] = (
      await pool.query<{ n: number }>(`SELECT count(*)::int AS n FROM ${table}`)
    ).rows[0].n;
  }
  return out;
}

async function sessionDigest(pool: Pool): Promise<string> {
  const rows = await pool.query(
    "SELECT space_id, user_id, agent_id, session_id, messages, revision FROM pi_sessions ORDER BY 1, 2, 3, 4",
  );
  return sha(JSON.stringify(rows.rows));
}

async function seed(url: string): Promise<State> {
  const pool = new Pool({ connectionString: url, max: 4 });
  try {
    await migrateDatabase(pool);
    const ledger = new RunLedger(pool);
    const space = `space_${randomUUID().slice(0, 8)}`;
    const user = `user_${randomUUID().slice(0, 8)}`;
    await pool.query("INSERT INTO web_users (id, name) VALUES ($1, $1)", [user]);

    // A run a crashed worker was holding: leased to a dead worker, lease already expired.
    const stale = await ledger.create({
      spaceId: space,
      userId: user,
      workflowId: "analytics",
      workflowVersion: "1",
      input: { q: "stale" },
      idempotencyKey: "stale",
    });
    await pool.query(
      `UPDATE platform_runs SET status = 'running', worker_id = 'dead-worker', fencing_token = 5,
         lease_until = now() - interval '5 minutes' WHERE id = $1`,
      [stale.id],
    );
    const queued = await ledger.create({
      spaceId: space,
      userId: user,
      workflowId: "analytics",
      workflowVersion: "1",
      input: { q: "queued" },
      idempotencyKey: "queued",
    });
    for (let index = 0; index < 3; index += 1) {
      await ledger.appendEvent({
        runId: queued.id,
        spaceId: space,
        userId: user,
        eventType: "run.status",
        payload: { index },
      });
    }

    const artifacts = new ArtifactStorage(pool);
    const stored = [];
    for (const [kind, content] of [
      [
        "dataset",
        Buffer.from(
          JSON.stringify({ rows: Array.from({ length: 200 }, (_, i) => ({ i, v: i * 1.5 })) }),
        ),
      ],
      ["report", Buffer.from("# Q3\nRevenue rose 12%.\n", "utf8")],
      ["binary", Buffer.from(Array.from({ length: 4096 }, (_, i) => (i * 37) % 256))],
    ] as const) {
      const result = await artifacts.store({
        workspaceId: space,
        ownerRunId: queued.id,
        kind,
        version: "1",
        content,
      });
      stored.push({ id: result.id, sha256: result.sha256, bytes: result.bytes });
    }

    await pool.query(
      `INSERT INTO pi_sessions (space_id, user_id, agent_id, session_id, messages, revision)
       VALUES ($1, $2, 'analytics', 's1', $3::jsonb, 4)`,
      [
        space,
        user,
        JSON.stringify([
          { role: "user", content: "hi" },
          { role: "assistant", content: "hello" },
        ]),
      ],
    );

    const receipts = new TerminalReceiptStorage(pool);
    const receiptInput = { run: queued.id, q: "sealed" };
    const receipt = await receipts.seal({
      workspaceId: space,
      runId: queued.id,
      attemptId: "att_1",
      status: "success",
      input: receiptInput,
      output: { ok: true },
      artifactIds: stored.map(({ id }) => id),
      evidenceCount: 3,
      verifiedEvidenceCount: 3,
      durationMs: 1200,
    });

    const pendingOutbox = (
      await pool.query<{ n: number }>(
        "SELECT count(*)::int AS n FROM platform_outbox_events WHERE published_at IS NULL",
      )
    ).rows[0].n;
    const seqs = await pool.query<{ run_id: string; max: string }>(
      "SELECT run_id, max(seq) AS max FROM platform_run_events WHERE run_id = ANY($1) GROUP BY run_id",
      [[stale.id, queued.id]],
    );

    return {
      seededAt: new Date().toISOString(),
      space,
      user,
      counts: await counts(pool),
      artifacts: stored,
      staleRunId: stale.id,
      queuedRunId: queued.id,
      idempotencyKey: "queued",
      pendingOutbox,
      receiptInput,
      receiptId: receipt.id,
      sessionDigest: await sessionDigest(pool),
      maxEventSeq: Object.fromEntries(seqs.rows.map((row) => [row.run_id, Number(row.max)])),
    };
  } finally {
    await pool.end();
  }
}

type Check = { name: string; ok: boolean; detail?: unknown };

async function verify(url: string, state: State): Promise<Check[]> {
  const pool = new Pool({ connectionString: url, max: 4 });
  const checks: Check[] = [];
  const check = (name: string, ok: boolean, detail?: unknown) =>
    checks.push({ name, ok, ...(detail !== undefined && { detail }) });
  try {
    const restored = await counts(pool);
    const diff = Object.entries(state.counts).filter(([table, n]) => restored[table] !== n);
    check(
      "row counts match the source",
      diff.length === 0,
      diff.length ? { expected: state.counts, restored } : undefined,
    );

    const status = await migrationStatus(pool);
    check(
      "schema matches this build (no pending, no unknown)",
      status.pending.length === 0 && status.unknown.length === 0,
      status,
    );

    // Artifact bytes: recompute from the restored content, not from the stored hash column.
    const artifacts = new ArtifactStorage(pool);
    const mismatched = [];
    for (const expected of state.artifacts) {
      const content = await artifacts.getContent(expected.id, state.space);
      const actual = content ? { sha256: sha(content), bytes: content.length } : null;
      if (!actual || actual.sha256 !== expected.sha256 || actual.bytes !== expected.bytes)
        mismatched.push({ expected, actual });
      if (!(await artifacts.verify({ id: expected.id, sha256: expected.sha256 })))
        mismatched.push({ id: expected.id, verify: false });
    }
    check(
      `artifact hash+length readback (${state.artifacts.length})`,
      mismatched.length === 0,
      mismatched.length ? mismatched : undefined,
    );

    check("session rows byte-identical", (await sessionDigest(pool)) === state.sessionDigest);

    // Sequences must continue past restored data, or new rows collide with restored ids.
    const outboxBefore = (
      await pool.query<{ max: string }>("SELECT max(id) AS max FROM platform_outbox_events")
    ).rows[0].max;
    const ledger = new RunLedger(pool);
    await ledger.appendEvent({
      runId: state.queuedRunId,
      spaceId: state.space,
      userId: state.user,
      eventType: "rehearsal.probe",
      payload: {},
    });
    const next = await pool.query<{ seq: string }>(
      "SELECT max(seq) AS seq FROM platform_run_events WHERE run_id = $1",
      [state.queuedRunId],
    );
    const outboxAfter = (
      await pool.query<{ max: string }>("SELECT max(id) AS max FROM platform_outbox_events")
    ).rows[0].max;
    check(
      "event seq and outbox id sequences continue after restore",
      Number(next.rows[0].seq) === state.maxEventSeq[state.queuedRunId] + 1 &&
        Number(outboxAfter) > Number(outboxBefore ?? 0),
      { seq: Number(next.rows[0].seq), outboxBefore, outboxAfter },
    );

    // Recovery: a lease held by a worker that no longer exists is re-claimed with a new fencing token.
    let reclaimed: { id: string; fencing_token: string } | undefined;
    for (let attempt = 0; attempt < 20 && !reclaimed; attempt += 1) {
      const claimed = await ledger.claim("rehearsal-worker", 30_000);
      if (!claimed) break;
      if (claimed.id === state.staleRunId) reclaimed = claimed;
    }
    check(
      "stale lease from a dead worker is re-claimed with a higher fencing token",
      Boolean(reclaimed) && Number(reclaimed?.fencing_token) > 5,
      reclaimed ? { fencing_token: reclaimed.fencing_token } : undefined,
    );
    if (reclaimed) {
      const zombie = await ledger.transition(
        state.staleRunId,
        "dead-worker",
        "5",
        "running",
        "completed",
      );
      check("the dead worker's old fencing token can no longer write", zombie === false);
    }

    // Outbox: everything unpublished at backup time is delivered after restore, once each.
    const delivered = new Map<string, number>();
    const publisher = new OutboxPublisher(
      pool,
      async (event) => {
        delivered.set(String(event.id), (delivered.get(String(event.id)) ?? 0) + 1);
      },
      { publisherId: "rehearsal-outbox", batchSize: 500 },
    );
    for (let round = 0; round < 20 && (await publisher.publishOnce()) > 0; round += 1) {
      // drain
    }
    const second = new OutboxPublisher(
      pool,
      async (event) => {
        delivered.set(String(event.id), (delivered.get(String(event.id)) ?? 0) + 1);
      },
      { publisherId: "rehearsal-outbox-2", batchSize: 500 },
    );
    await second.publishOnce();
    const left = (
      await pool.query<{ n: number }>(
        "SELECT count(*)::int AS n FROM platform_outbox_events WHERE published_at IS NULL",
      )
    ).rows[0].n;
    const duplicates = [...delivered.values()].filter((n) => n > 1).length;
    check(
      "outbox pending at backup is delivered after restore, each event once",
      left === 0 && duplicates === 0 && delivered.size >= state.pendingOutbox,
      { pendingAtBackup: state.pendingOutbox, delivered: delivered.size, duplicates, left },
    );

    // Effects: re-sending a request whose run survived the restore must not create a second run.
    const replay = await ledger.create({
      spaceId: state.space,
      userId: state.user,
      workflowId: "analytics",
      workflowVersion: "1",
      input: { q: "queued" },
      idempotencyKey: state.idempotencyKey,
    });
    check("idempotent request replays to the restored run", replay.id === state.queuedRunId, {
      replay: replay.id,
    });

    const receipts = new TerminalReceiptStorage(pool);
    const replayCheck = await receipts.checkReplay(state.space, state.receiptInput);
    check(
      "sealed terminal receipt is found for its input, so the effect is not re-run",
      replayCheck.exists && replayCheck.existingReceipt?.id === state.receiptId,
      { exists: replayCheck.exists, id: replayCheck.existingReceipt?.id },
    );
    return checks;
  } finally {
    await pool.end();
  }
}

const [mode, url, statePath] = process.argv.slice(2);
if (!url)
  throw new Error("usage: rehearse-backup-restore.ts seed|verify <database-url> [state.json]");
guard(url);
if (mode === "seed") {
  const state = await seed(url);
  writeFileSync(statePath ?? "/dev/stdout", JSON.stringify(state, null, 2));
} else if (mode === "verify") {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as State;
  const checks = await verify(url, state);
  process.stdout.write(
    `${JSON.stringify({ checks, ok: checks.every((entry) => entry.ok) }, null, 2)}\n`,
  );
  if (!checks.every((entry) => entry.ok)) process.exitCode = 1;
} else {
  throw new Error(`unknown mode '${mode}'`);
}
