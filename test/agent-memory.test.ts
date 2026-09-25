import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrateDatabase } from "../src/database.js";
import { PostgresAgentMemoryProvider, PostgresPiSessionStore } from "../src/postgres-store.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 4 });
  await migrateDatabase(database);
});

afterAll(async () => {
  await database?.end();
});

integration("PostgreSQL agent state", () => {
  it("keeps durable memory private to its space, user, and agent", async () => {
    const base = {
      userId: randomUUID(),
      spaceId: randomUUID(),
      agentId: "agent-a",
      signal: new AbortController().signal,
    };
    const firstWorker = new PostgresAgentMemoryProvider(database);
    await firstWorker.remember({ text: "North revenue rises", tags: ["north"] }, base);

    const restartedWorker = new PostgresAgentMemoryProvider(database);
    expect(await restartedWorker.search("north", base)).toHaveLength(1);
    expect(await restartedWorker.search("north", { ...base, agentId: "agent-b" })).toEqual([]);
    expect(await restartedWorker.search("north", { ...base, userId: randomUUID() })).toEqual([]);
    expect(await restartedWorker.search("north", { ...base, spaceId: randomUUID() })).toEqual([]);

    await database.query("DELETE FROM agent_memory_entries WHERE space_id = $1 AND user_id = $2", [
      base.spaceId,
      base.userId,
    ]);
  });

  it("searches memory in PostgreSQL and bounds ranked results to eight entries", async () => {
    const scope = {
      userId: randomUUID(),
      spaceId: randomUUID(),
      agentId: "agent-search",
      signal: new AbortController().signal,
    };
    const memory = new PostgresAgentMemoryProvider(database);
    for (let index = 0; index < 25; index += 1) {
      await memory.remember(
        { text: `bounded memory note ${index}`, tags: ["search-check"] },
        scope,
      );
    }

    const results = await memory.search("bounded memory note", scope);

    expect(results).toHaveLength(8);
    expect(results[0]?.text).toBe("bounded memory note 24");
    expect(results.at(-1)?.text).toBe("bounded memory note 17");
    await database.query("DELETE FROM agent_memory_entries WHERE space_id = $1 AND user_id = $2", [
      scope.spaceId,
      scope.userId,
    ]);
  });

  it("updates stable memory keys, ranks matching notes, and forgets only within the agent scope", async () => {
    const scope = {
      userId: randomUUID(),
      spaceId: randomUUID(),
      agentId: "agent-lifecycle",
      signal: new AbortController().signal,
    };
    const memory = new PostgresAgentMemoryProvider(database);
    await memory.remember(
      { key: "sales-preference", text: "Prefers monthly revenue charts" },
      scope,
    );
    await memory.remember(
      { key: "sales-preference", text: "Prefers monthly revenue charts by region" },
      scope,
    );
    await memory.remember({ key: "unrelated", text: "Uses concise status summaries" }, scope);

    const results = await memory.search("monthly revenue region", scope);
    const result = results[0];

    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({
      key: "sales-preference",
      text: "Prefers monthly revenue charts by region",
    });
    if (!result) throw new Error("Expected matching memory result");
    expect(await memory.forget(result.id, { ...scope, agentId: "other-agent" })).toBe(false);
    expect(await memory.forget(result.id, scope)).toBe(true);
    expect(await memory.search("monthly revenue region", scope)).toEqual([]);
    await database.query("DELETE FROM agent_memory_entries WHERE space_id = $1 AND user_id = $2", [
      scope.spaceId,
      scope.userId,
    ]);
  });

  it("persists Pi history and acquires a cross-worker session lock", async () => {
    const store = new PostgresPiSessionStore(database);
    const scope = {
      userId: randomUUID(),
      spaceId: randomUUID(),
      agentId: "agent-a",
      sessionId: randomUUID(),
    };
    const firstWorker = await store.open(scope);
    const initial = await firstWorker.load();
    const messages = [{ role: "user", content: "remember this", timestamp: 1 }] as never[];

    await expect(store.open(scope)).rejects.toThrow("already has an active run");
    expect(await firstWorker.save(messages, initial.revision)).toBe(1);
    await firstWorker.release();

    const restartedWorker = await new PostgresPiSessionStore(database).open(scope);
    expect(await restartedWorker.load()).toEqual({ messages, revision: 1 });
    await restartedWorker.release();
    await database.query("DELETE FROM pi_sessions WHERE space_id = $1 AND user_id = $2", [
      scope.spaceId,
      scope.userId,
    ]);
  });
});
