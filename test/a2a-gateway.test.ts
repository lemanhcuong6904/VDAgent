/**
 * A2A gateway - M12.5
 * Wire contract (A2A 1.0 JSON-RPC), auth/tenant mapping, rate limit and version
 * negotiation. The PostgreSQL block is the evidence that an external caller reaches
 * only its own tasks and that retries and reconnects are safe.
 */

import { createHash, randomUUID } from "node:crypto";
import { Hono } from "hono";
import { Pool } from "pg";
import { Type } from "typebox";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import {
  A2A_ERRORS,
  type A2aClient,
  acceptMessage,
  authenticateA2a,
  buildAgentCard,
  mapTaskState,
  parseA2aClients,
  registerA2aGateway,
} from "../src/a2a-gateway.js";
import { migrateDatabase } from "../src/database.js";
import { AgentPool } from "../src/registry.js";
import { RunLedger } from "../src/run-ledger.js";

const sha = (value: string) => createHash("sha256").update(value).digest("hex");

function registry(...ids: string[]) {
  const pool = new AgentPool();
  for (const id of ids) {
    pool.register({
      descriptor: {
        id,
        version: "1.0.0",
        name: `Agent ${id}`,
        description: `Does ${id} things`,
        capabilities: [`${id}.work`],
        input: Type.Object({}),
        tools: [],
      },
      async run() {
        return {};
      },
    });
  }
  return pool;
}

function client(overrides: Partial<A2aClient> = {}): A2aClient {
  return {
    id: "partner-a",
    tokenSha256: sha("token-a"),
    userId: "user_a",
    spaceId: "space_a",
    skills: ["analytics"],
    rateLimit: 60,
    ...overrides,
  };
}

describe("client config", () => {
  it("parses a valid entry and defaults the rate limit", () => {
    const [parsed] = parseA2aClients(
      JSON.stringify([
        { id: "p", tokenSha256: sha("t"), userId: "u", spaceId: "s", skills: ["analytics"] },
      ]),
    );
    expect(parsed.rateLimit).toBe(60);
  });

  it("refuses a plaintext token, an empty skill list and a duplicate id", () => {
    const base = {
      id: "p",
      tokenSha256: sha("t"),
      userId: "u",
      spaceId: "s",
      skills: ["analytics"],
    };
    expect(() => parseA2aClients(JSON.stringify([{ ...base, tokenSha256: "token-a" }]))).toThrow(
      /sha256/,
    );
    expect(() => parseA2aClients(JSON.stringify([{ ...base, skills: [] }]))).toThrow(/skills/);
    expect(() => parseA2aClients(JSON.stringify([base, base]))).toThrow(/duplicate/);
  });

  it("treats an unset variable as no clients", () => {
    expect(parseA2aClients(undefined)).toEqual([]);
  });
});

describe("authentication", () => {
  const clients = [
    client(),
    client({ id: "partner-b", tokenSha256: sha("token-b"), userId: "user_b" }),
  ];

  it("maps a token to exactly its client", () => {
    expect(authenticateA2a("Bearer token-b", clients)?.id).toBe("partner-b");
    expect(authenticateA2a("bearer token-a", clients)?.id).toBe("partner-a");
  });

  it("rejects a missing, malformed or unknown token", () => {
    expect(authenticateA2a(undefined, clients)).toBeUndefined();
    expect(authenticateA2a("token-a", clients)).toBeUndefined();
    expect(authenticateA2a("Bearer nope", clients)).toBeUndefined();
    expect(authenticateA2a(`Bearer ${sha("token-a")}`, clients)).toBeUndefined();
  });
});

describe("agent card", () => {
  it("advertises only configured skills, with the 1.0 required fields", () => {
    const card = buildAgentCard({
      pluginRegistry: registry("analytics", "internal-admin"),
      clients: [client()],
      publicUrl: "https://agents.example/",
    });
    expect(card.skills.map((skill) => skill.id)).toEqual(["analytics"]);
    expect(card.skills[0]).toEqual({
      id: "analytics",
      name: "Agent analytics",
      description: "Does analytics things",
      tags: ["analytics.work"],
    });
    expect(card.supportedInterfaces).toEqual([
      { url: "https://agents.example/a2a", protocolBinding: "JSONRPC", protocolVersion: "1.0" },
    ]);
    for (const field of [
      "name",
      "description",
      "version",
      "capabilities",
      "defaultInputModes",
      "defaultOutputModes",
    ]) {
      expect(card).toHaveProperty(field);
    }
    expect(card.capabilities.pushNotifications).toBe(false);
  });

  it("does not advertise a configured skill that is not registered", () => {
    const card = buildAgentCard({
      pluginRegistry: registry(),
      clients: [client()],
      publicUrl: "http://x",
    });
    expect(card.skills).toEqual([]);
  });
});

describe("message intake", () => {
  const message = (overrides: Record<string, unknown> = {}) => ({
    messageId: "m1",
    role: "ROLE_USER",
    parts: [{ text: "hello" }],
    ...overrides,
  });

  it("joins text and data parts", () => {
    expect(acceptMessage(message({ parts: [{ text: "rows:" }, { data: { a: 1 } }] })).text).toBe(
      'rows:\n{"a":1}',
    );
  });

  it("refuses file parts with ContentTypeNotSupported", () => {
    expect(() => acceptMessage(message({ parts: [{ url: "https://x/file.csv" }] }))).toThrow(
      expect.objectContaining({ code: A2A_ERRORS.contentTypeNotSupported }),
    );
  });

  it("refuses an agent-role message, a continuation and oversized content", () => {
    expect(() => acceptMessage(message({ role: "ROLE_AGENT" }))).toThrow(
      expect.objectContaining({ code: A2A_ERRORS.invalidParams }),
    );
    expect(() => acceptMessage(message({ taskId: "t1" }))).toThrow(
      expect.objectContaining({ code: A2A_ERRORS.unsupportedOperation }),
    );
    expect(() => acceptMessage(message({ parts: [{ text: "x".repeat(4_001) }] }))).toThrow(
      /at most 4000/,
    );
  });
});

describe("state mapping", () => {
  it("lets the invocation decide terminal state before the run", () => {
    expect(mapTaskState("completed", "running")).toBe("TASK_STATE_WORKING");
    expect(mapTaskState("completed", "completed")).toBe("TASK_STATE_COMPLETED");
    expect(mapTaskState("failed", "failed")).toBe("TASK_STATE_FAILED");
    expect(mapTaskState("running", "rejected")).toBe("TASK_STATE_REJECTED");
    expect(mapTaskState("cancelled", "queued")).toBe("TASK_STATE_CANCELED");
    expect(mapTaskState("queued", "queued")).toBe("TASK_STATE_SUBMITTED");
    expect(mapTaskState("waiting", null)).toBe("TASK_STATE_WORKING");
  });
});

describe("JSON-RPC surface (no database)", () => {
  function app(clients = [client()]) {
    const query = vi.fn(async () => ({ rows: [] }));
    const hono = new Hono();
    registerA2aGateway(hono, {
      database: { query, connect: vi.fn() } as never,
      pluginRegistry: registry("analytics"),
      runLedger: {} as never,
      clients,
      publicUrl: "http://localhost",
    });
    return { hono, query };
  }

  const call = (
    hono: Hono,
    method: string,
    params: unknown = {},
    headers: Record<string, string> = {},
  ) =>
    hono.request("/a2a", {
      method: "POST",
      headers: {
        authorization: "Bearer token-a",
        "a2a-version": "1.0",
        "content-type": "application/json",
        ...headers,
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 7, method, params }),
    });

  it("serves the card at the well-known path", async () => {
    const response = await app().hono.request("/.well-known/agent-card.json");
    expect(response.status).toBe(200);
    expect(((await response.json()) as { skills: unknown[] }).skills).toHaveLength(1);
  });

  it("answers 401 with a challenge and touches nothing without a token", async () => {
    const { hono, query } = app();
    const response = await call(hono, "GetTask", { id: "a2a_x" }, { authorization: "" });
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("Bearer");
    expect(query).not.toHaveBeenCalled();
  });

  it("treats a missing A2A-Version as 0.3 and refuses it", async () => {
    const response = await call(app().hono, "GetTask", { id: "a2a_x" }, { "a2a-version": "" });
    await expect(response.json()).resolves.toMatchObject({
      id: 7,
      error: { code: A2A_ERRORS.versionNotSupported },
    });
  });

  it("maps unsupported operations to their specific codes", async () => {
    const { hono } = app();
    const codes = await Promise.all(
      ["ListTasks", "CreateTaskPushNotificationConfig", "GetExtendedAgentCard", "message/send"].map(
        async (method) => {
          const body = (await (await call(hono, method)).json()) as { error: { code: number } };
          return body.error.code;
        },
      ),
    );
    expect(codes).toEqual([
      A2A_ERRORS.unsupportedOperation,
      A2A_ERRORS.pushNotSupported,
      A2A_ERRORS.extendedCardNotConfigured,
      A2A_ERRORS.methodNotFound,
    ]);
  });

  it("reports a parse error and an invalid envelope distinctly", async () => {
    const { hono } = app();
    const broken = await hono.request("/a2a", {
      method: "POST",
      headers: { authorization: "Bearer token-a", "a2a-version": "1.0" },
      body: "{",
    });
    await expect(broken.json()).resolves.toMatchObject({ error: { code: A2A_ERRORS.parse } });
    const invalid = await hono.request("/a2a", {
      method: "POST",
      headers: { authorization: "Bearer token-a", "a2a-version": "1.0" },
      body: JSON.stringify({ method: "GetTask" }),
    });
    await expect(invalid.json()).resolves.toMatchObject({
      error: { code: A2A_ERRORS.invalidRequest },
    });
  });

  it("rate limits per client, independently of other clients", async () => {
    const { hono } = app([
      client({ rateLimit: 2 }),
      client({ id: "partner-b", tokenSha256: sha("token-b"), rateLimit: 2 }),
    ]);
    const statuses = [];
    for (let index = 0; index < 3; index += 1)
      statuses.push((await call(hono, "ListTasks")).status);
    expect(statuses).toEqual([200, 200, 429]);
    expect((await call(hono, "ListTasks", {}, { authorization: "Bearer token-b" })).status).toBe(
      200,
    );
  });

  it("does not leak internal error detail", async () => {
    const hono = new Hono();
    registerA2aGateway(hono, {
      database: {
        query: vi.fn(async () => {
          throw new Error("relation a2a_tasks at 10.0.0.9 password=hunter2");
        }),
      } as never,
      pluginRegistry: registry("analytics"),
      runLedger: {} as never,
      clients: [client()],
      publicUrl: "http://localhost",
    });
    const text = await (await call(hono, "GetTask", { id: "a2a_x" })).text();
    expect(text).toContain(String(A2A_ERRORS.internal));
    expect(text).not.toMatch(/hunter2|10\.0\.0\.9/);
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("A2A gateway - M12.5 (PostgreSQL)", () => {
  let database: Pool;
  let hono: Hono;
  const suffix = randomUUID().slice(0, 8);
  const partnerA = client({ id: `pa_${suffix}`, userId: `ua_${suffix}`, spaceId: `sa_${suffix}` });
  const partnerB = client({
    id: `pb_${suffix}`,
    tokenSha256: sha("token-b"),
    userId: `ub_${suffix}`,
    spaceId: `sb_${suffix}`,
  });

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 8 });
    await migrateDatabase(database);
    for (const partner of [partnerA, partnerB]) {
      await database.query(
        "INSERT INTO web_users (id, name) VALUES ($1, $1) ON CONFLICT DO NOTHING",
        [partner.userId],
      );
    }
    hono = new Hono();
    registerA2aGateway(hono, {
      database,
      pluginRegistry: registry("analytics"),
      runLedger: new RunLedger(database),
      clients: [partnerA, partnerB],
      publicUrl: "http://localhost",
      streamPollMs: 20,
      streamMaxMs: 5_000,
    });
  });

  afterAll(async () => {
    for (const partner of [partnerA, partnerB]) {
      await database?.query("DELETE FROM a2a_tasks WHERE client_id = $1", [partner.id]);
      await database?.query("DELETE FROM web_messages WHERE user_id = $1", [partner.userId]);
      await database?.query("DELETE FROM web_invocations WHERE user_id = $1", [partner.userId]);
      await database?.query("UPDATE web_tasks SET platform_run_id = NULL WHERE user_id = $1", [
        partner.userId,
      ]);
      await database?.query("DELETE FROM platform_runs WHERE user_id = $1", [partner.userId]);
      await database?.query("DELETE FROM web_tasks WHERE user_id = $1", [partner.userId]);
      await database?.query("DELETE FROM web_events WHERE user_id = $1", [partner.userId]);
      await database?.query("DELETE FROM web_users WHERE id = $1", [partner.userId]);
    }
    await database?.end();
  });

  const call = (
    method: string,
    params: unknown,
    token = "token-a",
    headers: Record<string, string> = {},
  ) =>
    hono.request("/a2a", {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        "a2a-version": "1.0",
        "content-type": "application/json",
        ...headers,
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    });

  const send = async (messageId: string, text = "revenue by month", token = "token-a") =>
    (await (
      await call(
        "SendMessage",
        { message: { messageId, role: "ROLE_USER", parts: [{ text }] } },
        token,
      )
    ).json()) as {
      result?: {
        task: { id: string; contextId: string; status: { state: string }; history: unknown[] };
      };
      error?: { code: number };
    };

  /** Stand-in for the durable worker finishing the invocation it was given. */
  async function finish(taskId: string, reply: string) {
    const row = await database.query<{ run_id: string; web_task_id: string }>(
      "SELECT run_id, web_task_id FROM a2a_tasks WHERE id = $1",
      [taskId],
    );
    const { run_id: runId, web_task_id: webTaskId } = row.rows[0];
    await database.query(
      "UPDATE platform_runs SET status = 'running', updated_at = now() WHERE id = $1",
      [runId],
    );
    await database.query("UPDATE web_invocations SET status = 'running' WHERE task_id = $1", [
      webTaskId,
    ]);
    await new Promise((resolve) => setTimeout(resolve, 80));
    await database.query(
      "UPDATE web_invocations SET status = 'completed', result_text = $2, finished_at = now() WHERE task_id = $1",
      [webTaskId, reply],
    );
    await database.query(
      "UPDATE platform_runs SET status = 'completed', finished_at = now(), updated_at = now() WHERE id = $1",
      [runId],
    );
  }

  it("creates a task on the durable path under the client's mapped user and space", async () => {
    const body = await send(`m_${randomUUID()}`);
    const task = body.result?.task;
    expect(task?.status.state).toBe("TASK_STATE_SUBMITTED");
    expect(task?.history).toHaveLength(1);
    const row = await database.query(
      `SELECT r.space_id, r.user_id, r.workflow_id, r.status FROM a2a_tasks a JOIN platform_runs r ON r.id = a.run_id
       WHERE a.id = $1`,
      [task?.id],
    );
    expect(row.rows[0]).toEqual({
      space_id: partnerA.spaceId,
      user_id: partnerA.userId,
      workflow_id: "web.agent_message",
      status: "queued",
    });
  });

  it("returns the same task for a retried messageId, even concurrently", async () => {
    const messageId = `m_${randomUUID()}`;
    const results = await Promise.all(Array.from({ length: 4 }, () => send(messageId)));
    expect(new Set(results.map((result) => result.result?.task.id)).size).toBe(1);
    const count = await database.query(
      "SELECT count(*)::int AS n FROM a2a_tasks WHERE client_id = $1 AND message_id = $2",
      [partnerA.id, messageId],
    );
    expect(count.rows[0].n).toBe(1);
  });

  it("refuses a reused messageId carrying different content", async () => {
    const messageId = `m_${randomUUID()}`;
    await send(messageId, "first");
    const second = await send(messageId, "second");
    expect(second.error?.code).toBe(A2A_ERRORS.invalidParams);
  });

  it("hides one client's task from another, as TaskNotFound", async () => {
    const mine = await send(`m_${randomUUID()}`);
    const probe = (await (
      await call("GetTask", { id: mine.result?.task.id }, "token-b")
    ).json()) as {
      error?: { code: number };
    };
    expect(probe.error?.code).toBe(A2A_ERRORS.taskNotFound);
    const cancel = (await (
      await call("CancelTask", { id: mine.result?.task.id }, "token-b")
    ).json()) as {
      error?: { code: number };
    };
    expect(cancel.error?.code).toBe(A2A_ERRORS.taskNotFound);
  });

  it("cancels a live task once and refuses a second cancel", async () => {
    const task = (await send(`m_${randomUUID()}`)).result?.task;
    const first = (await (await call("CancelTask", { id: task?.id })).json()) as {
      result?: { status: { state: string } };
    };
    expect(first.result?.status.state).toBe("TASK_STATE_CANCELED");
    const second = (await (await call("CancelTask", { id: task?.id })).json()) as {
      error?: { code: number };
    };
    expect(second.error?.code).toBe(A2A_ERRORS.taskNotCancelable);
  });

  it("streams the task to completion and a resubscribe after the drop sees the final state", async () => {
    const created = (await send(`m_${randomUUID()}`)).result?.task;
    const taskId = created?.id as string;
    const streamed = hono.request("/a2a", {
      method: "POST",
      headers: {
        authorization: "Bearer token-a",
        "a2a-version": "1.0",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 9,
        method: "SubscribeToTask",
        params: { id: taskId },
      }),
    });
    setTimeout(() => void finish(taskId, "Revenue rose 12% in March."), 40);
    const frames = (await (await streamed).text())
      .split("\n\n")
      .map((block) =>
        block
          .split("\n")
          .find((line) => line.startsWith("data:"))
          ?.slice(5)
          .trim(),
      )
      .filter((data): data is string => Boolean(data))
      .map(
        (data) =>
          JSON.parse(data) as {
            id: number;
            result: Record<string, { status?: { state: string } }>;
          },
      );

    expect(frames[0].result).toHaveProperty("task");
    expect(frames.every((frame) => frame.id === 9)).toBe(true);
    const states = frames.flatMap((frame) =>
      frame.result.statusUpdate ? [frame.result.statusUpdate.status?.state] : [],
    );
    expect(states.at(-1)).toBe("TASK_STATE_COMPLETED");
    expect(frames.some((frame) => "artifactUpdate" in frame.result)).toBe(true);

    // A client that dropped mid-stream reconnects and gets the terminal snapshot first.
    const again = await (
      await hono.request("/a2a", {
        method: "POST",
        headers: { authorization: "Bearer token-a", "a2a-version": "1.0" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 10,
          method: "SubscribeToTask",
          params: { id: taskId },
        }),
      })
    ).text();
    const snapshot = JSON.parse(
      again
        .split("\n")
        .find((line) => line.startsWith("data:"))
        ?.slice(5) ?? "{}",
    ) as {
      result: {
        task: {
          status: { state: string; message: { parts: { text: string }[] } };
          artifacts: unknown[];
        };
      };
    };
    expect(snapshot.result.task.status.state).toBe("TASK_STATE_COMPLETED");
    expect(snapshot.result.task.status.message.parts[0].text).toBe("Revenue rose 12% in March.");
    expect(snapshot.result.task.artifacts).toHaveLength(1);
  });
});
