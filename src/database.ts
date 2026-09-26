import { readFile } from "node:fs/promises";
import type { Pool } from "pg";

const MIGRATIONS = [
  {
    version: "001_agent_memory_and_pi_sessions",
    url: "../db/migrations/001_agent_memory_and_pi_sessions.sql",
  },
  { version: "002_web_workflow", url: "../db/migrations/002_web_workflow.sql" },
  { version: "003_invocation_tree", url: "../db/migrations/003_invocation_tree.sql" },
  { version: "004_agent_memory_search", url: "../db/migrations/004_agent_memory_search.sql" },
  { version: "005_agent_memory_lifecycle", url: "../db/migrations/005_agent_memory_lifecycle.sql" },
  { version: "006_platform_runtime", url: "../db/migrations/006_platform_runtime.sql" },
  { version: "007_durable_web_runs", url: "../db/migrations/007_durable_web_runs.sql" },
  { version: "008_agent_message_runs", url: "../db/migrations/008_agent_message_runs.sql" },
  { version: "009_web_event_cursor", url: "../db/migrations/009_web_event_cursor.sql" },
  { version: "010_usage_outbox_claims", url: "../db/migrations/010_usage_outbox_claims.sql" },
];
const MIGRATION_LOCK_KEY = 6_041_002;

export async function migrateDatabase(pool: Pool): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query("SELECT pg_advisory_lock($1)", [MIGRATION_LOCK_KEY]);
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

      const sql = await readFile(new URL(migration.url, import.meta.url), "utf8");
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
      await client.query("SELECT pg_advisory_unlock($1)", [MIGRATION_LOCK_KEY]);
    } finally {
      client.release();
    }
  }
}
