import os from "node:os";
import { Pool } from "pg";
import { AlertScheduler, AlertStore } from "./alerts.js";
import { migrateDatabase, migrationStatus } from "./database.js";
import { Lifecycle } from "./lifecycle.js";
import { OutboxPublisher } from "./outbox.js";
import { createOutboxFanout } from "./outbox-consumers.js";
import { loadPlatformServices } from "./platform-services.js";
import { RunLedger } from "./run-ledger.js";
import { DurableRunWorker } from "./run-worker.js";
import { createWebTaskRunExecutor } from "./web-api.js";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is required");

const database = new Pool({ connectionString: databaseUrl, max: 20 });
database.on("error", (error) => {
  process.stderr.write(`PostgreSQL pool error: ${error.message}\n`);
});
await migrateDatabase(database, {
  lockTimeoutMs: positiveInt(process.env.MIGRATION_LOCK_TIMEOUT_MS, 120_000),
});

const services = await loadPlatformServices(database);
const ledger = new RunLedger(database);
const workerName = process.env.WORKER_ID || `${os.hostname()}-${process.pid}`;
const worker = new DurableRunWorker(
  ledger,
  createWebTaskRunExecutor({
    database,
    pluginRegistry: services.pluginRegistry,
    pool: services.pool,
    runtime: services.runtime,
    catalog: services.catalog,
  }),
  {
    workerId: workerName,
    leaseMs: positiveInt(process.env.WORKER_LEASE_MS, 30_000),
    pollMs: positiveInt(process.env.WORKER_POLL_MS, 250),
    concurrency: positiveInt(process.env.WORKER_CONCURRENCY, 4),
  },
);
const outboxFanout = createOutboxFanout();
const outbox = new OutboxPublisher(database, outboxFanout.dispatch, {
  publisherId: `outbox-${workerName}`,
  pollMs: positiveInt(process.env.OUTBOX_POLL_MS, 250),
});

// ALERT_EVAL_INTERVAL_MS=0 disables scheduled evaluation (e.g. when an external cron runs it).
const alertIntervalMs = Number(process.env.ALERT_EVAL_INTERVAL_MS ?? 60_000);
const alerts =
  alertIntervalMs > 0
    ? new AlertScheduler(new AlertStore(database), alertIntervalMs, (error) =>
        process.stderr.write(
          `${JSON.stringify({ message: "alerts.evaluation_failed", error: error instanceof Error ? error.message : "unknown" })}\n`,
        ),
      )
    : undefined;

const lifecycle = new Lifecycle({
  ping: () => database.query("SELECT 1"),
  migrations: () => migrationStatus(database),
});
// Worker drains before the outbox stops, so events from runs finishing in the grace
// window are still published; the pool closes last (M13.1).
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    void lifecycle
      .shutdown(
        [
          {
            name: "worker",
            run: () => worker.drain(positiveInt(process.env.WORKER_DRAIN_GRACE_MS, 20_000)),
          },
          { name: "outbox", run: () => outbox.stop() },
          { name: "alerts", run: async () => alerts?.stop() },
          { name: "tracing", run: () => services.shutdownTracing() },
          { name: "memory-retention", run: () => services.shutdownMemoryRetention() },
          { name: "warehouse-database", run: () => services.shutdownWarehouse() },
          { name: "database", run: () => database.end() },
        ],
        { drainDelayMs: 0, timeoutMs: positiveInt(process.env.SHUTDOWN_TIMEOUT_MS, 30_000) },
      )
      .then((result) => {
        process.stdout.write(`${JSON.stringify({ message: "platform.shutdown", ...result })}\n`);
        process.exit(result.ok ? 0 : 1);
      });
  });
}

outbox.start();
worker.start();
alerts?.start();
lifecycle.markReady();
process.stdout.write(`Team 6 cAi worker started as ${workerName}\n`);
await new Promise<void>(() => undefined);

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
