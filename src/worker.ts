import os from "node:os";
import { Pool } from "pg";
import { migrateDatabase } from "./database.js";
import { OutboxPublisher } from "./outbox.js";
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
await migrateDatabase(database);

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
const outbox = new OutboxPublisher(
  database,
  async (event) => {
    process.stdout.write(
      `${JSON.stringify({
        message: "platform.outbox_published",
        outbox_id: event.id,
        run_id: event.run_id,
        event_type: event.event_type,
      })}\n`,
    );
  },
  {
    publisherId: `outbox-${workerName}`,
    pollMs: positiveInt(process.env.OUTBOX_POLL_MS, 250),
  },
);

let stopping = false;
const shutdown = async () => {
  if (stopping) return;
  stopping = true;
  await outbox.stop();
  await worker.stop();
  await database.end();
};
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    void shutdown().finally(() => process.exit(0));
  });
}

outbox.start();
worker.start();
process.stdout.write(`Team 6 cAi worker started as ${workerName}\n`);
await new Promise<void>(() => undefined);

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
