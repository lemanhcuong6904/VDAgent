import { readFile } from "node:fs/promises";
import type { Pool, PoolClient } from "pg";
import { loadMigrationChain } from "./migration-chain.js";

// Revision order lives in versions.json (`pnpm versions`), not in file names.
const MIGRATIONS = loadMigrationChain().map(({ revision, file }) => ({
  version: revision,
  url: new URL(`../${file}`, import.meta.url),
}));

const MIGRATION_LOCK_KEY = 6_041_002;

export const KNOWN_MIGRATIONS: readonly string[] = MIGRATIONS.map(({ version }) => version);

export class MigrationLockTimeoutError extends Error {
  constructor(waitedMs: number) {
    super(`Timed out after ${waitedMs}ms waiting for the migration lock`);
    this.name = "MigrationLockTimeoutError";
  }
}

/**
 * Take the migration advisory lock, waiting at most `timeoutMs`. A replica that
 * cannot get it fails startup loudly instead of hanging behind a stuck migrator.
 */
async function acquireMigrationLock(
  client: PoolClient,
  timeoutMs: number,
  pollMs = 250,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = await client.query<{ locked: boolean }>(
      "SELECT pg_try_advisory_lock($1) AS locked",
      [MIGRATION_LOCK_KEY],
    );
    if (result.rows[0]?.locked) return;
    if (Date.now() >= deadline) throw new MigrationLockTimeoutError(timeoutMs);
    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(pollMs, Math.max(1, deadline - Date.now()))),
    );
  }
}

export interface MigrationStatus {
  /** Migrations this build knows but the database has not applied. */
  pending: string[];
  /** Migrations the database has that this build does not know: a newer build ran. */
  unknown: string[];
}

/** Compare the applied migrations with this build's list, without taking the lock. */
export async function migrationStatus(pool: Pick<Pool, "query">): Promise<MigrationStatus> {
  const table = await pool.query<{ exists: boolean }>(
    "SELECT to_regclass('public.schema_migrations') IS NOT NULL AS exists",
  );
  const applied = table.rows[0]?.exists
    ? (await pool.query<{ version: string }>("SELECT version FROM schema_migrations")).rows.map(
        (row) => row.version,
      )
    : [];
  const appliedSet = new Set(applied);
  const known = new Set(KNOWN_MIGRATIONS);
  return {
    pending: KNOWN_MIGRATIONS.filter((version) => !appliedSet.has(version)),
    unknown: applied.filter((version) => !known.has(version)).sort(),
  };
}

export async function migrateDatabase(
  pool: Pool,
  options: { lockTimeoutMs?: number } = {},
): Promise<void> {
  const client = await pool.connect();
  let locked = false;
  try {
    await acquireMigrationLock(client, options.lockTimeoutMs ?? 120_000);
    locked = true;
    await client.query(
      `CREATE TABLE IF NOT EXISTS schema_migrations (
        version text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )`,
    );
    for (const migration of MIGRATIONS) {
      const applied = await client.query("SELECT 1 FROM schema_migrations WHERE version = $1", [
        migration.version,
      ]);
      if (applied.rowCount) continue;

      const sql = await readFile(migration.url, "utf8");
      await client.query("BEGIN");
      try {
        await client.query(sql);
        await client.query("INSERT INTO schema_migrations (version) VALUES ($1)", [
          migration.version,
        ]);
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK").catch(() => undefined);
        throw error;
      }
    }
  } finally {
    try {
      if (locked) await client.query("SELECT pg_advisory_unlock($1)", [MIGRATION_LOCK_KEY]);
    } finally {
      client.release();
    }
  }
}
