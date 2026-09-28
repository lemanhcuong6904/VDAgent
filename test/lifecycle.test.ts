/**
 * Process lifecycle - M13.1
 * Readiness semantics, ordered shutdown, worker drain and the migration lock.
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import {
  KNOWN_MIGRATIONS,
  MigrationLockTimeoutError,
  migrateDatabase,
  migrationStatus,
} from "../src/database.js";
import { Lifecycle } from "../src/lifecycle.js";
import { DurableRunWorker } from "../src/run-worker.js";

const healthy = { pending: [], unknown: [] };

describe("readiness", () => {
  it("is not ready while starting, even when every dependency is fine", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    expect(await lifecycle.readiness()).toMatchObject({ ready: false, phase: "starting" });
    lifecycle.markReady();
    expect(await lifecycle.readiness()).toMatchObject({
      ready: true,
      checks: { database: "ok", schema: "ok" },
    });
  });

  it("drops out when the database is unreachable, without throwing", async () => {
    const lifecycle = new Lifecycle({
      ping: async () => {
        throw new Error("ECONNREFUSED");
      },
      migrations: async () => healthy,
    });
    lifecycle.markReady();
    const report = await lifecycle.readiness();
    expect(report).toMatchObject({ ready: false, checks: { database: "unreachable" } });
    expect(JSON.stringify(report)).not.toContain("ECONNREFUSED");
  });

  it("refuses traffic when the schema is behind or ahead of this build", async () => {
    const behind = new Lifecycle({
      ping: async () => 1,
      migrations: async () => ({ pending: ["017_a2a_tasks"], unknown: [] }),
    });
    behind.markReady();
    expect(await behind.readiness()).toMatchObject({
      ready: false,
      checks: { schema: "pending" },
      pending: ["017_a2a_tasks"],
    });

    const ahead = new Lifecycle({
      ping: async () => 1,
      migrations: async () => ({ pending: [], unknown: ["018_future"] }),
    });
    ahead.markReady();
    expect(await ahead.readiness()).toMatchObject({
      ready: false,
      checks: { schema: "ahead" },
      unknown: ["018_future"],
    });
  });

  it("reports not ready from the moment draining starts", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    lifecycle.markReady();
    let observed: boolean | undefined;
    await lifecycle.shutdown(
      [{ name: "probe", run: async () => (observed = (await lifecycle.readiness()).ready) }],
      { drainDelayMs: 0, timeoutMs: 1_000 },
    );
    expect(observed).toBe(false);
    expect(lifecycle.phase).toBe("stopped");
  });
});

describe("ordered shutdown", () => {
  it("runs steps in order and still closes later steps after one fails", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    const order: string[] = [];
    const result = await lifecycle.shutdown(
      [
        { name: "http", run: async () => order.push("http") },
        {
          name: "worker",
          run: async () => {
            order.push("worker");
            throw new Error("drain failed");
          },
        },
        { name: "database", run: async () => order.push("database") },
      ],
      { drainDelayMs: 0, timeoutMs: 1_000 },
    );
    expect(order).toEqual(["http", "worker", "database"]);
    expect(result.ok).toBe(false);
    expect(result.steps.map((step) => [step.name, step.ok])).toEqual([
      ["http", true],
      ["worker", false],
      ["database", true],
    ]);
  });

  it("gives up at the timeout instead of hanging on a stuck step", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    const started = Date.now();
    const result = await lifecycle.shutdown(
      [{ name: "stuck", run: () => new Promise(() => undefined) }],
      {
        drainDelayMs: 0,
        timeoutMs: 50,
      },
    );
    expect(result).toMatchObject({ ok: false, timedOut: true });
    expect(Date.now() - started).toBeLessThan(1_000);
  });

  it("waits the drain delay before the first step", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    const started = Date.now();
    let firstStepAt = 0;
    await lifecycle.shutdown([{ name: "http", run: async () => (firstStepAt = Date.now()) }], {
      drainDelayMs: 60,
      timeoutMs: 1_000,
    });
    expect(firstStepAt - started).toBeGreaterThanOrEqual(55);
  });

  it("ignores a second signal", async () => {
    const lifecycle = new Lifecycle({ ping: async () => 1, migrations: async () => healthy });
    const step = vi.fn(async () => undefined);
    await lifecycle.shutdown([{ name: "a", run: step }], { drainDelayMs: 0, timeoutMs: 1_000 });
    await lifecycle.shutdown([{ name: "a", run: step }], { drainDelayMs: 0, timeoutMs: 1_000 });
    expect(step).toHaveBeenCalledOnce();
  });
});

describe("worker drain", () => {
  function run(id: string) {
    return {
      id,
      space_id: "s",
      user_id: "u",
      workflow_id: "w",
      workflow_version: "1",
      status: "queued" as const,
      input: {},
      attempt: 1,
      fencing_token: "1",
      lease_until: new Date(Date.now() + 30_000),
    };
  }

  function worker(durationMs: number, claims: number) {
    let remaining = claims;
    const transitions: string[] = [];
    const ledger = {
      async claim() {
        if (remaining <= 0) return undefined;
        remaining -= 1;
        return run(`run_${remaining}`);
      },
      async heartbeat() {
        return true;
      },
      async transition(_id: string, _worker: string, _token: string, from: string, to: string) {
        transitions.push(`${from}->${to}`);
        return true;
      },
    } as never;
    const executor = {
      execute: (_run: unknown, signal: AbortSignal) =>
        new Promise((resolve, reject) => {
          const timer = setTimeout(() => resolve({ ok: true }), durationMs);
          signal.addEventListener("abort", () => {
            clearTimeout(timer);
            reject(signal.reason);
          });
        }),
    };
    return {
      instance: new DurableRunWorker(ledger, executor, {
        workerId: "w1",
        concurrency: 2,
        pollMs: 5,
      }),
      transitions,
    };
  }

  async function until(check: () => boolean) {
    for (let index = 0; index < 200 && !check(); index += 1)
      await new Promise((resolve) => setTimeout(resolve, 5));
  }

  it("lets in-flight runs complete within the grace and claims nothing new", async () => {
    const { instance, transitions } = worker(40, 5);
    instance.start();
    await until(() => instance.activeCount === 2);
    const result = await instance.drain(1_000);
    expect(result).toEqual({ finished: 2, handedBack: 0 });
    expect(transitions.filter((entry) => entry === "running->completed")).toHaveLength(2);
    expect(transitions).not.toContain("running->retryable");
  });

  it("hands runs back as retryable when they outlast the grace", async () => {
    const { instance, transitions } = worker(10_000, 2);
    instance.start();
    await until(() => instance.activeCount === 2);
    const result = await instance.drain(30);
    expect(result).toEqual({ finished: 0, handedBack: 2 });
    expect(transitions.filter((entry) => entry === "running->retryable")).toHaveLength(2);
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("migrations - M13.1 (PostgreSQL)", () => {
  let database: Pool;

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 6 });
    await migrateDatabase(database);
  });

  afterAll(async () => {
    await database?.end();
  });

  it("reports a fully migrated schema", async () => {
    await expect(migrationStatus(database)).resolves.toEqual({ pending: [], unknown: [] });
  });

  it("is idempotent when several replicas migrate concurrently", async () => {
    await Promise.all(Array.from({ length: 4 }, () => migrateDatabase(database)));
    const rows = await database.query("SELECT count(*)::int AS n FROM schema_migrations");
    expect(rows.rows[0].n).toBeGreaterThanOrEqual(KNOWN_MIGRATIONS.length);
  });

  it("times out instead of hanging when another process holds the lock", async () => {
    const holder = await database.connect();
    try {
      await holder.query("SELECT pg_advisory_lock(6041002)");
      const started = Date.now();
      await expect(migrateDatabase(database, { lockTimeoutMs: 300 })).rejects.toBeInstanceOf(
        MigrationLockTimeoutError,
      );
      expect(Date.now() - started).toBeLessThan(3_000);
    } finally {
      await holder.query("SELECT pg_advisory_unlock(6041002)");
      holder.release();
    }
    // The failed attempt must not have left the lock held.
    await expect(migrateDatabase(database, { lockTimeoutMs: 1_000 })).resolves.toBeUndefined();
  });

  it("flags a schema written by a newer build", async () => {
    const future = `999_future_${randomUUID().slice(0, 6)}`;
    await database.query("INSERT INTO schema_migrations (version) VALUES ($1)", [future]);
    try {
      await expect(migrationStatus(database)).resolves.toEqual({ pending: [], unknown: [future] });
    } finally {
      await database.query("DELETE FROM schema_migrations WHERE version = $1", [future]);
    }
  });
});
