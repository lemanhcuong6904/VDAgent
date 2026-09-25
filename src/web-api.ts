import { randomUUID } from "node:crypto";
import type { Context, Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import type { Pool, PoolClient } from "pg";
import { Value } from "typebox/value";
import type { AgentPlugin } from "./agent-contract.js";
import { greetingReply } from "./agent-guardrails.js";
import type { PiRuntime } from "./pi-runtime.js";
import type { AgentPool } from "./registry.js";
import type { McpToolPool } from "./tool-pool.js";

type Dependencies = {
  database: Pool;
  pluginRegistry: AgentPool;
  pool: McpToolPool;
  runtime: PiRuntime;
};

type UiEvent = { event: string; data: Record<string, unknown> };
type Subscriber = { queue: UiEvent[]; wake: (() => void) | undefined; closed: boolean };

const subscriptions = new Map<string, Set<Subscriber>>();
const activeTasks = new Map<string, AbortController>();
export function registerWebApi(app: Hono, dependencies: Dependencies): void {
  const { database, pluginRegistry, pool, runtime } = dependencies;

  app.get("/api/users", async (context) => {
    const result = await database.query(
      "SELECT id, name FROM web_users ORDER BY created_at DESC, id DESC",
    );
    return context.json(result.rows);
  });

  app.post("/api/users", async (context) => {
    const body = await context.req.json().catch(() => undefined);
    if (!isRecord(body) || typeof body.name !== "string" || !body.name.trim()) {
      return error(context, 422, "invalid_request", "name must not be empty");
    }
    const user = {
      id: `u_${randomUUID().replaceAll("-", "").slice(0, 12)}`,
      name: body.name.trim().slice(0, 120),
    };
    await database.query("INSERT INTO web_users (id, name) VALUES ($1, $2)", [user.id, user.name]);
    return context.json(user, 201);
  });

  app.get("/api/agents", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const busy = await database.query<{ agent: string; count: string }>(
      `SELECT agent, count(*)::text AS count FROM web_invocations
       WHERE user_id = $1 AND status = 'running' GROUP BY agent`,
      [user.id],
    );
    const activeInvocations = new Map(busy.rows.map((row) => [row.agent, Number(row.count)]));
    const agents = pluginRegistry.list().map((agent) => ({
      name: agent.id,
      description: agent.description,
      healthy: true,
      busy: (activeInvocations.get(agent.id) ?? 0) > 0,
      queue_len: 0,
    }));
    return context.json(agents);
  });

  app.get("/api/agents/:agent/messages", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const agent = context.req.param("agent");
    if (!resolveAgent(pluginRegistry, agent))
      return error(context, 404, "unknown_agent", "Unknown agent");
    const before = Number(context.req.query("before_seq") ?? Number.MAX_SAFE_INTEGER);
    const limit = Math.min(200, Math.max(1, Number(context.req.query("limit") ?? 50)));
    if (!Number.isSafeInteger(before) || before < 1 || !Number.isSafeInteger(limit)) {
      return error(context, 422, "invalid_request", "Invalid message page");
    }
    const result = await database.query(
      `SELECT id, seq, task_id, invocation_id, role, sender, content, created_at
       FROM web_messages WHERE user_id = $1 AND agent = $2 AND seq < $3::bigint
       ORDER BY seq DESC LIMIT $4`,
      [user.id, agent, before, limit],
    );
    const messages = result.rows.reverse().map(messageDto);
    return context.json({ summary: null, messages, pending: [] });
  });

  app.post("/api/agents/:agent/messages", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const agent = context.req.param("agent");
    const plugin = resolveAgent(pluginRegistry, agent);
    if (!plugin) return error(context, 404, "unknown_agent", "Unknown agent");
    const body = await context.req.json().catch(() => undefined);
    if (!isRecord(body) || typeof body.content !== "string" || !body.content.trim()) {
      return error(context, 422, "invalid_request", "content must not be empty");
    }
    const content = body.content.trim().slice(0, 20_000);
    const taskId = `t_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
    const invocationId = `inv_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
    const client = await database.connect();
    await client.query("BEGIN");
    try {
      await client.query(
        "INSERT INTO web_tasks (id, user_id, root_agent, status) VALUES ($1, $2, $3, 'running')",
        [taskId, user.id, agent],
      );
      await client.query(
        `INSERT INTO web_invocations (id, task_id, user_id, agent, caller, inbound_text, status, started_at)
         VALUES ($1, $2, $3, $4, 'user', $5, 'running', now())`,
        [invocationId, taskId, user.id, agent, content],
      );
      const savedUserMessage = await writeMessage(client, {
        userId: user.id,
        agent,
        taskId,
        invocationId,
        role: "user",
        content,
      });
      await client.query("COMMIT");
      publish(user.id, "message.appended", { agent, message: messageDto(savedUserMessage) });
    } catch (failure) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw failure;
    } finally {
      client.release();
    }
    publish(user.id, "task.updated", { task: await getTask(database, taskId) });
    publish(user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
    const controller = new AbortController();
    activeTasks.set(taskId, controller);
    void runTask({
      database,
      plugin,
      pool,
      runtime,
      user,
      agent,
      taskId,
      invocationId,
      content,
      controller,
    });
    return context.json({ task_id: taskId, invocation_id: invocationId }, 202);
  });

  app.get("/api/tasks", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const status = context.req.query("status");
    if (status && !["running", "completed", "failed", "cancelled"].includes(status)) {
      return error(context, 422, "invalid_request", "Invalid task status");
    }
    const result = await database.query(
      `SELECT id, root_agent, status, created_at, finished_at FROM web_tasks
       WHERE user_id = $1 AND ($2::text IS NULL OR status = $2) ORDER BY created_at DESC LIMIT 50`,
      [user.id, status ?? null],
    );
    return context.json(result.rows.map(taskDto));
  });

  app.get("/api/tasks/:taskId", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const taskId = context.req.param("taskId");
    const [task, invocations] = await Promise.all([
      database.query(
        "SELECT id, root_agent, status, created_at, finished_at FROM web_tasks WHERE id = $1 AND user_id = $2",
        [taskId, user.id],
      ),
      database.query(
        `SELECT id, task_id, agent, caller, parent_id, tool_call_id,
          depth, inbound_text, status, result_text, error, created_at, started_at, finished_at
         FROM web_invocations WHERE task_id = $1 AND user_id = $2 ORDER BY created_at`,
        [taskId, user.id],
      ),
    ]);
    if (!task.rowCount) return error(context, 404, "not_found", "Task not found");
    return context.json({ task: taskDto(task.rows[0]), invocations: invocations.rows });
  });

  app.post("/api/tasks/:taskId/cancel", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const taskId = context.req.param("taskId");
    const result = await database.query(
      `UPDATE web_tasks SET status = 'cancelled', finished_at = now()
       WHERE id = $1 AND user_id = $2 AND status = 'running'
       RETURNING id, root_agent, status, created_at, finished_at`,
      [taskId, user.id],
    );
    if (!result.rowCount) return error(context, 409, "task_finished", "Task already finished");
    activeTasks.get(taskId)?.abort("task cancelled");
    const task = taskDto(result.rows[0]);
    publish(user.id, "task.updated", { task });
    return context.json({ task });
  });

  app.get("/api/events", async (context) => {
    const userId = context.req.query("user_id");
    if (
      !userId ||
      !(await database.query("SELECT 1 FROM web_users WHERE id = $1", [userId])).rowCount
    ) {
      return error(context, 401, "user_required", "Select a valid user first");
    }
    const subscriber: Subscriber = { queue: [], wake: undefined, closed: false };
    const group = subscriptions.get(userId) ?? new Set<Subscriber>();
    group.add(subscriber);
    subscriptions.set(userId, group);
    return streamSSE(context, async (stream) => {
      try {
        while (!subscriber.closed && !context.req.raw.signal.aborted) {
          const event = subscriber.queue.shift();
          if (!event) {
            let onAbort: () => void = () => undefined;
            await new Promise<void>((resolve) => {
              subscriber.wake = resolve;
              onAbort = () => resolve();
              context.req.raw.signal.addEventListener("abort", onAbort, { once: true });
            });
            context.req.raw.signal.removeEventListener("abort", onAbort);
            subscriber.wake = undefined;
            continue;
          }
          await stream.writeSSE({ event: event.event, data: JSON.stringify(event.data) });
        }
      } finally {
        subscriber.closed = true;
        group.delete(subscriber);
        if (!group.size) subscriptions.delete(userId);
      }
    });
  });

  app.get("/api/reports", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const result = await database.query(
      `SELECT id, title, created_at FROM web_reports WHERE user_id = $1
       ORDER BY created_at DESC LIMIT 100`,
      [user.id],
    );
    return context.json(
      result.rows.map((row) => ({
        id: row.id,
        title: row.title,
        created_at: new Date(row.created_at).toISOString(),
      })),
    );
  });
  app.get("/api/datasets/:id", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const offset = Math.max(0, Number(context.req.query("offset") ?? 0));
    const limit = Math.min(1000, Math.max(1, Number(context.req.query("limit") ?? 200)));
    const result = await database.query(
      `SELECT id, name, columns, rows, source_sql FROM web_datasets
       WHERE id = $1 AND user_id = $2`,
      [context.req.param("id"), user.id],
    );
    const dataset = result.rows[0];
    if (!dataset) return error(context, 404, "not_found", "Dataset not found");
    const rows = dataset.rows as Record<string, unknown>[];
    const columns = dataset.columns as Array<{ name: string; type: string }>;
    return context.json({
      id: dataset.id,
      name: dataset.name,
      columns,
      row_count: rows.length,
      truncated: false,
      source_sql: dataset.source_sql,
      rows: rows.slice(offset, offset + limit).map((row) => columns.map(({ name }) => row[name])),
    });
  });
  app.get("/api/charts/:id", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const result = await database.query(
      "SELECT id, title, dataset_id, spec FROM web_charts WHERE id = $1 AND user_id = $2",
      [context.req.param("id"), user.id],
    );
    const chart = result.rows[0];
    if (!chart) return error(context, 404, "not_found", "Chart not found");
    return context.json(chart);
  });
  app.get("/api/reports/:id", async (context) => {
    const user = await requireUser(context, database);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const result = await database.query(
      `SELECT id, title, markdown, created_at FROM web_reports WHERE id = $1 AND user_id = $2`,
      [context.req.param("id"), user.id],
    );
    const report = result.rows[0];
    if (!report) return error(context, 404, "not_found", "Report not found");
    return context.json({ ...report, created_at: new Date(report.created_at).toISOString() });
  });
}

async function runTask(input: {
  database: Pool;
  plugin: AgentPlugin;
  pool: McpToolPool;
  runtime: PiRuntime;
  user: { id: string };
  agent: string;
  taskId: string;
  invocationId: string;
  content: string;
  controller: AbortController;
}): Promise<void> {
  const {
    database,
    plugin,
    pool,
    runtime,
    user,
    agent,
    taskId,
    invocationId,
    content,
    controller,
  } = input;
  if (!plugin) return;
  publish(user.id, "task.updated", { task: await getTask(database, taskId) });
  try {
    const pluginInput = { prompt: content };
    if (!Value.Check(plugin.descriptor.input, pluginInput))
      throw new Error("Message does not match agent input");
    const output =
      greetingReply(content) ??
      (await plugin.run(pluginInput, {
        runId: invocationId,
        sessionId: `web:${user.id}:${agent}`,
        userId: user.id,
        spaceId: process.env.API_SPACE_ID ?? "local-space",
        taskId,
        depth: 0,
        signal: controller.signal,
        tools: pool.forNames(plugin.descriptor.tools),
        runtime,
        pool,
        publish,
      }));
    const contentText = renderOutput(output);
    const saved = await insertMessage(database, {
      userId: user.id,
      agent,
      taskId,
      invocationId,
      role: "assistant",
      content: contentText,
    });
    await database.query(
      `UPDATE web_invocations SET status = 'completed', result_text = $2, finished_at = now() WHERE id = $1`,
      [invocationId, contentText],
    );
    const finished = await database.query(
      `UPDATE web_tasks SET status = 'completed', finished_at = now() WHERE id = $1
       RETURNING id, root_agent, status, created_at, finished_at`,
      [taskId],
    );
    publish(user.id, "message.appended", { agent, message: messageDto(saved) });
    publish(user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
    publish(user.id, "task.updated", { task: taskDto(finished.rows[0]) });
  } catch (failure) {
    const cancelled = controller.signal.aborted;
    const reason = failure instanceof Error ? failure.message : "Agent run failed";
    await database.query(
      `UPDATE web_invocations SET status = $2, error = $3, finished_at = now() WHERE id = $1`,
      [invocationId, cancelled ? "cancelled" : "failed", reason],
    );
    const finished = await database.query(
      `UPDATE web_tasks SET status = $2, finished_at = now() WHERE id = $1
       RETURNING id, root_agent, status, created_at, finished_at`,
      [taskId, cancelled ? "cancelled" : "failed"],
    );
    publish(user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
    if (finished.rows[0]) publish(user.id, "task.updated", { task: taskDto(finished.rows[0]) });
  } finally {
    activeTasks.delete(taskId);
  }
}

async function insertMessage(
  database: Pool,
  input: {
    userId: string;
    agent: string;
    taskId: string;
    invocationId: string;
    role: string;
    content: string;
  },
) {
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    const saved = await writeMessage(client, input);
    await client.query("COMMIT");
    return saved;
  } catch (failure) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw failure;
  } finally {
    client.release();
  }
}

async function writeMessage(
  client: PoolClient,
  input: {
    userId: string;
    agent: string;
    taskId: string;
    invocationId: string;
    role: string;
    sender?: string | null;
    content: string;
  },
) {
  await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
    `${input.userId}:${input.agent}`,
  ]);
  const seq = await client.query<{ seq: number }>(
    "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM web_messages WHERE user_id = $1 AND agent = $2",
    [input.userId, input.agent],
  );
  const saved = await client.query(
    `INSERT INTO web_messages (user_id, agent, seq, task_id, invocation_id, role, sender, content)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     RETURNING id, seq, task_id, invocation_id, role, sender, content, created_at`,
    [
      input.userId,
      input.agent,
      seq.rows[0]?.seq ?? 1,
      input.taskId,
      input.invocationId,
      input.role,
      input.role === "user" ? (input.sender ?? "user") : null,
      input.content,
    ],
  );
  return saved.rows[0];
}

async function requireUser(context: Context, database: Pool) {
  const userId = context.req.header("x-user-id");
  if (!userId) return undefined;
  const result = await database.query("SELECT id, name FROM web_users WHERE id = $1", [userId]);
  return result.rows[0] as { id: string; name: string } | undefined;
}

async function getTask(database: Pool, taskId: string) {
  const result = await database.query(
    "SELECT id, root_agent, status, created_at, finished_at FROM web_tasks WHERE id = $1",
    [taskId],
  );
  return taskDto(result.rows[0]);
}

async function getInvocation(database: Pool, invocationId: string) {
  const result = await database.query(
    `SELECT id, task_id, agent, caller, NULL::text AS parent_id, NULL::text AS tool_call_id,
      depth, inbound_text, status, result_text, error, created_at, started_at, finished_at
     FROM web_invocations WHERE id = $1`,
    [invocationId],
  );
  return result.rows[0];
}

function resolveAgent(registry: AgentPool, agent: string) {
  return registry.get(agent);
}

function messageDto(row: Record<string, unknown>) {
  return {
    id: Number(row.id),
    seq: Number(row.seq),
    task_id: row.task_id,
    invocation_id: row.invocation_id,
    role: row.role,
    sender: row.sender,
    content: row.content,
    tool_calls: null,
    tool_call_id: null,
    compacted: false,
    created_at: new Date(row.created_at as string | Date).toISOString(),
  };
}

function taskDto(row: Record<string, unknown>) {
  return {
    id: row.id,
    root_agent: row.root_agent,
    status: row.status,
    created_at: new Date(row.created_at as string | Date).toISOString(),
    finished_at: row.finished_at ? new Date(row.finished_at as string | Date).toISOString() : null,
  };
}

function renderOutput(output: unknown): string {
  if (typeof output === "string") return output;
  if (isRecord(output) && typeof output.report === "string") return output.report;
  return JSON.stringify(output, null, 2);
}

function publish(userId: string, event: string, data: Record<string, unknown>) {
  for (const subscriber of subscriptions.get(userId) ?? []) {
    if (subscriber.queue.length >= 1000) {
      subscriber.closed = true;
      subscriber.wake?.();
      subscriptions.get(userId)?.delete(subscriber);
      continue;
    }
    subscriber.queue.push({ event, data });
    subscriber.wake?.();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function error(context: Context, status: number, code: string, message: string) {
  return context.json({ error: { code, message } }, status as ContentfulStatusCode);
}
