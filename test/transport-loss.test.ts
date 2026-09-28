/**
 * Transport loss and rebuild from PostgreSQL - M13.4
 *
 * The platform has no Redis or broker. Its non-durable transport is the in-process
 * SSE fan-out in `web-api.ts`. These tests show that losing it (another replica, a
 * separate worker process, a restart) loses no event: delivery is rebuilt from
 * `web_events`, in order, once.
 */

import { randomUUID } from "node:crypto";
import { Hono } from "hono";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { migrateDatabase } from "../src/database.js";
import { AgentPool } from "../src/registry.js";
import { EventTail, registerWebApi } from "../src/web-api.js";
import { issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

describe("EventTail", () => {
  function fakeDb(rows: () => Array<{ id: number; late?: boolean }>) {
    return {
      query: vi.fn(async (_sql: string, params: unknown[]) => {
        const [, cursor, floor] = params as [string, number, number];
        return {
          rows: rows()
            .filter((row) => row.id > cursor || (row.id > floor && row.late))
            .map((row) => ({ id: String(row.id), event: "task.updated", data: { id: row.id } })),
        };
      }),
    };
  }

  it("delivers a row that became visible after a higher id, and only once", async () => {
    const visible: Array<{ id: number; late?: boolean }> = [{ id: 5 }, { id: 7 }];
    const tail = new EventTail(fakeDb(() => visible) as never, "u", 4);
    expect((await tail.next()).map((row) => row.id)).toEqual([5, 7]);
    // id 6 commits late: its transaction took the id before 7 but committed after.
    visible.push({ id: 6, late: true });
    expect((await tail.next()).map((row) => row.id)).toEqual([6]);
    expect(await tail.next()).toEqual([]);
  });

  it("never re-sends anything at or below the client's resume cursor", async () => {
    const tail = new EventTail(fakeDb(() => [{ id: 3, late: true }, { id: 9 }]) as never, "u", 3);
    expect((await tail.next()).map((row) => row.id)).toEqual([9]);
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

// collect() may wait its full 5s deadline under load; the test budget must exceed it.
describe.skipIf(!databaseUrl)(
  "SSE across processes - M13.4 (PostgreSQL)",
  { timeout: 15_000 },
  () => {
    const webAuth: WebAuthConfig = {
      mode: "session",
      secret: "transport-loss-signing-key-000000",
      ttlSeconds: 600,
    };
    const userId = `user_${randomUUID().slice(0, 8)}`;
    let database: Pool;

    beforeAll(async () => {
      database = new Pool({ connectionString: databaseUrl, max: 8 });
      await migrateDatabase(database);
      await database.query(
        "INSERT INTO web_users (id, name) VALUES ($1, $1) ON CONFLICT DO NOTHING",
        [userId],
      );
    });

    afterAll(async () => {
      await database?.query("DELETE FROM web_events WHERE user_id = $1", [userId]);
      await database?.query("DELETE FROM web_users WHERE id = $1", [userId]);
      await database?.end();
    });

    /** One API replica: its own module-level subscriptions are irrelevant here; only the DB is shared. */
    function replica() {
      const app = new Hono();
      registerWebApi(app, {
        database,
        pluginRegistry: new AgentPool(),
        pool: {} as never,
        runtime: {} as never,
        webAuth,
        eventPollMs: 50,
      });
      return app;
    }

    /** Simulates an emit from another process: the row exists, no local publish happens. */
    async function emitElsewhere(tag: string): Promise<number> {
      const result = await database.query<{ id: string }>(
        "INSERT INTO web_events (user_id, event, data) VALUES ($1, 'task.updated', $2::jsonb) RETURNING id",
        [userId, JSON.stringify({ task: { id: tag, status: "running" } })],
      );
      return Number(result.rows[0].id);
    }

    /** Open the stream and collect frame ids until `want` arrive or the deadline passes. */
    async function collect(app: Hono, after: number, want: number, during?: () => Promise<void>) {
      const controller = new AbortController();
      const response = await app.request(`/api/events?user_id=${userId}&after=${after}`, {
        headers: { Authorization: `Bearer ${issueWebSession(userId, webAuth)}` },
        signal: controller.signal,
      });
      expect(response.status).toBe(200);
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      const ids: number[] = [];
      let buffer = "";
      const deadline = Date.now() + 5_000;
      void during?.();
      // Keep an unfinished read across ticks: abandoning it would drop the chunk it resolves with.
      let pending: ReturnType<typeof reader.read> | undefined;
      while (ids.length < want && Date.now() < deadline) {
        pending ??= reader.read();
        const chunk = await Promise.race([
          pending,
          new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 200)),
        ]);
        if (!chunk) continue;
        pending = undefined;
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        for (const match of buffer.matchAll(/^id: ?(\d+)$/gm)) {
          const id = Number(match[1]);
          if (!ids.includes(id)) ids.push(id);
        }
      }
      controller.abort();
      await reader.cancel().catch(() => undefined);
      return ids;
    }

    it("delivers live an event another process wrote, without a reconnect", async () => {
      const before = await emitElsewhere("warmup");
      const ids = await collect(replica(), before, 3, async () => {
        await new Promise((resolve) => setTimeout(resolve, 100));
        for (const tag of ["a", "b", "c"]) await emitElsewhere(tag);
      });
      expect(ids).toHaveLength(3);
      expect(ids.every((id) => id > before)).toBe(true);
      expect(ids).toEqual([...ids].sort((left, right) => left - right));
    });

    it("a subscriber on replica B sees events emitted while it was connected to replica A", async () => {
      const replicaA = replica();
      const replicaB = replica();
      const start = await emitElsewhere("start");
      const seenOnA = await collect(replicaA, start, 2, async () => {
        await emitElsewhere("a1");
        await emitElsewhere("a2");
      });
      // Replica A goes away. Two more events land while the client has no connection at all.
      const missed = [await emitElsewhere("gap1"), await emitElsewhere("gap2")];
      const seenOnB = await collect(replicaB, seenOnA.at(-1) as number, 2);
      expect(seenOnB).toEqual(missed);
      // No duplicate across the handover and no gap.
      const all = await database.query<{ id: string }>(
        "SELECT id FROM web_events WHERE user_id = $1 AND id > $2 ORDER BY id",
        [userId, start],
      );
      expect([...seenOnA, ...seenOnB]).toEqual(all.rows.map((row) => Number(row.id)));
    });

    it("concurrent writers from several processes are all delivered, once each", async () => {
      const start = await emitElsewhere("burst-start");
      const writers = 6;
      const perWriter = 10;
      const ids = await collect(replica(), start, writers * perWriter, async () => {
        await Promise.all(
          Array.from({ length: writers }, async (_, writer) => {
            for (let index = 0; index < perWriter; index += 1)
              await emitElsewhere(`w${writer}-${index}`);
          }),
        );
      });
      expect(ids).toHaveLength(writers * perWriter);
      expect(new Set(ids).size).toBe(ids.length);
    });
  },
);

describe.skipIf(!databaseUrl)("cancel across processes - M13.4 (PostgreSQL)", () => {
  const name = `rehearsal_cancel_${randomUUID().slice(0, 8)}`;
  let admin: Pool;
  let apiSide: Pool;
  let workerSide: Pool;

  beforeAll(async () => {
    admin = new Pool({ connectionString: databaseUrl, max: 1 });
    await admin.query(`CREATE DATABASE ${name}`);
    const url = new URL(databaseUrl as string);
    url.pathname = `/${name}`;
    // Two pools stand in for two processes: nothing in memory is shared between them.
    apiSide = new Pool({ connectionString: url.toString(), max: 4 });
    workerSide = new Pool({ connectionString: url.toString(), max: 4 });
    await migrateDatabase(apiSide);
  });

  afterAll(async () => {
    await apiSide?.end();
    await workerSide?.end();
    await admin?.query(`DROP DATABASE IF EXISTS ${name}`);
    await admin?.end();
  });

  it("a cancel written by the API stops a run executing in the worker process", async () => {
    const { RunLedger } = await import("../src/run-ledger.js");
    const { DurableRunWorker } = await import("../src/run-worker.js");
    const apiLedger = new RunLedger(apiSide);
    const workerLedger = new RunLedger(workerSide);
    const run = await apiLedger.create({
      spaceId: "s",
      userId: "u",
      workflowId: "long",
      workflowVersion: "1",
      input: {},
      idempotencyKey: `cancel-${randomUUID()}`,
    });
    let started = false;
    let abortedWith: unknown;
    const worker = new DurableRunWorker(
      workerLedger,
      {
        execute: (_claimed, signal) =>
          new Promise((_resolve, reject) => {
            started = true;
            signal.addEventListener("abort", () => {
              abortedWith = signal.reason;
              reject(signal.reason);
            });
          }),
      },
      { workerId: "worker-process", leaseMs: 3_000, pollMs: 20, concurrency: 1 },
    );
    worker.start();
    for (let index = 0; index < 100 && !started; index += 1)
      await new Promise((resolve) => setTimeout(resolve, 20));
    expect(started).toBe(true);

    const cancelledAt = Date.now();
    await expect(apiLedger.cancel(run.id, "s", "u")).resolves.toBe(true);
    let status = "";
    while (Date.now() - cancelledAt < 5_000) {
      status = (
        await apiSide.query<{ status: string }>("SELECT status FROM platform_runs WHERE id = $1", [
          run.id,
        ])
      ).rows[0].status;
      if (status === "cancelled") break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    await worker.drain(0);
    expect(status).toBe("cancelled");
    expect(abortedWith).toBeDefined();
    // Detected by the heartbeat, which runs every max(1s, lease/3).
    expect(Date.now() - cancelledAt).toBeLessThan(3_000);
  });
});
