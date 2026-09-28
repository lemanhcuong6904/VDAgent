import { randomUUID } from "node:crypto";
import type { Context, Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import type { Pool, PoolClient } from "pg";
import { Value } from "typebox/value";
import type { AgentPlugin } from "./agent-contract.js";
import { greetingReply } from "./agent-guardrails.js";
import { newTraceContext, type TraceContext } from "./observability.js";
import type { PiRuntime } from "./pi-runtime.js";
import type { AgentPool } from "./registry.js";
import type { ClaimedRun, RunLedger } from "./run-ledger.js";
import type { McpToolPool } from "./tool-pool.js";
import { bearerToken, verifyWebSession, type WebAuthConfig } from "./web-auth.js";

type Dependencies = {
  /** SSE poll interval for events written by other processes; tests shorten it. */
  eventPollMs?: number;
  database: Pool;
  pluginRegistry: AgentPool;
  pool: McpToolPool;
  runtime: PiRuntime;
  catalog?: import("./planner.js").PlannerCatalog;
  runLedger?: RunLedger;
  webAuth?: WebAuthConfig;
};

type UiEvent = { id?: number; event: string; data: Record<string, unknown> };
type Subscriber = { queue: UiEvent[]; wake: (() => void) | undefined; closed: boolean };

const subscriptions = new Map<string, Set<Subscriber>>();
const activeTasks = new Map<string, Set<AbortController>>();

function trackActiveTask(taskId: string, controller: AbortController): void {
  const controllers = activeTasks.get(taskId) ?? new Set<AbortController>();
  controllers.add(controller);
  activeTasks.set(taskId, controllers);
}

function untrackActiveTask(taskId: string, controller: AbortController): void {
  const controllers = activeTasks.get(taskId);
  if (!controllers) return;
  controllers.delete(controller);
  if (!controllers.size) activeTasks.delete(taskId);
}

function abortActiveTask(taskId: string, reason: string): void {
  for (const controller of activeTasks.get(taskId) ?? []) controller.abort(reason);
}
export function registerWebApi(app: Hono, dependencies: Dependencies): void {
  const { database, pluginRegistry, pool, runtime } = dependencies;
  const webAuth = dependencies.webAuth;

  app.get("/api/users", async (context) => {
    const authenticated = await authenticateUser(context, database, webAuth);
    if (webAuth?.mode === "session" && !authenticated) {
      return error(context, 401, "authentication_required", "A valid web session is required");
    }
    if (webAuth?.mode === "session" && authenticated) return context.json([authenticated]);
    const result = await database.query(
      "SELECT id, name FROM web_users ORDER BY created_at DESC, id DESC",
    );
    return context.json(result.rows);
  });

  app.post("/api/users", async (context) => {
    if (webAuth?.mode === "session") {
      return error(
        context,
        403,
        "user_provisioning_required",
        "Provision users through the identity provider",
      );
    }
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
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const agent = context.req.param("agent");
    const plugin = resolveAgent(pluginRegistry, agent);
    if (!plugin) return error(context, 404, "unknown_agent", "Unknown agent");
    const body = await context.req.json().catch(() => undefined);
    if (!isRecord(body) || typeof body.content !== "string" || !body.content.trim()) {
      return error(context, 422, "invalid_request", "content must not be empty");
    }
    const content = body.content.trim();
    if (content.length > 4_000) {
      return error(context, 422, "input_too_large", "content must be at most 4000 characters");
    }
    const runLedger = dependencies.runLedger;
    const durable = Boolean(runLedger);
    const client = await database.connect();
    let created: AgentMessageTask;
    await client.query("BEGIN");
    try {
      created = await createAgentMessageTaskOnClient(client, {
        userId: user.id,
        spaceId: process.env.API_SPACE_ID ?? "local-space",
        agent,
        content,
        runLedger,
      });
      await client.query("COMMIT");
      await emit(database, user.id, "message.appended", {
        agent,
        message: messageDto(created.userMessage),
      });
    } catch (failure) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw failure;
    } finally {
      client.release();
    }
    const { taskId, invocationId, runId } = created;
    const platformRun = runId ? { id: runId } : undefined;
    await emit(database, user.id, "task.updated", { task: await getTask(database, taskId) });
    await emit(database, user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
    if (!durable) {
      const controller = new AbortController();
      trackActiveTask(taskId, controller);
      void runTask({
        database,
        plugin,
        pool,
        runtime,
        // Default to the registry catalog so planning never depends on host wiring details.
        catalog: dependencies.catalog ?? pluginRegistry.plannerCatalog(),
        user,
        agent,
        taskId,
        invocationId,
        content,
        controller,
        trace: newTraceContext(),
      });
    }
    return context.json(
      {
        task_id: taskId,
        invocation_id: invocationId,
        ...(platformRun && { run_id: platformRun.id }),
      },
      202,
    );
  });

  app.get("/api/tasks", async (context) => {
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
    if (!user) return error(context, 401, "user_required", "Select a user first");
    const taskId = context.req.param("taskId");
    const result = await database.query(
      `UPDATE web_tasks SET status = 'cancelled', finished_at = now()
       WHERE id = $1 AND user_id = $2 AND status = 'running'
       RETURNING id, root_agent, status, created_at, finished_at, platform_run_id`,
      [taskId, user.id],
    );
    if (!result.rowCount) return error(context, 409, "task_finished", "Task already finished");
    const cancelledInvocations = await database.query<{ id: string }>(
      `UPDATE web_invocations SET status = 'cancelled', error = 'Task cancelled', finished_at = now()
       WHERE task_id = $1 AND user_id = $2 AND status IN ('queued', 'running')
       RETURNING id`,
      [taskId, user.id],
    );
    for (const invocation of cancelledInvocations.rows) {
      await emit(database, user.id, "invocation.updated", {
        invocation: await getInvocation(database, invocation.id),
      });
    }
    if (dependencies.runLedger) {
      const runs = await database.query<{ platform_run_id: string }>(
        `SELECT platform_run_id FROM web_invocations
         WHERE task_id = $1 AND user_id = $2 AND platform_run_id IS NOT NULL`,
        [taskId, user.id],
      );
      for (const run of runs.rows) {
        await dependencies.runLedger.cancel(
          run.platform_run_id,
          process.env.API_SPACE_ID ?? "local-space",
          user.id,
        );
      }
    }
    abortActiveTask(taskId, "task cancelled");
    const task = taskDto(result.rows[0]);
    await emit(database, user.id, "task.updated", { task });
    return context.json({ task });
  });

  app.get("/api/events", async (context) => {
    const userId = context.req.query("user_id");
    const authenticated = await authenticateUser(context, database, webAuth);
    if (!userId || !authenticated || authenticated.id !== userId) {
      return error(context, 401, "user_required", "Select a valid user first");
    }
    const cursorHeader = context.req.header("last-event-id");
    const cursorQuery = context.req.query("after");
    const cursor = parseCursor(cursorQuery ?? cursorHeader);
    if (cursor === undefined) return error(context, 422, "invalid_cursor", "Invalid event cursor");
    const subscriber: Subscriber = { queue: [], wake: undefined, closed: false };
    const group = subscriptions.get(userId) ?? new Set<Subscriber>();
    group.add(subscriber);
    subscriptions.set(userId, group);
    // PostgreSQL is the only delivery source (M13.4). A local publish only wakes the
    // loop early; the poll interval covers events written by another API replica or
    // by the worker process, which a process-local publish can never reach.
    const pollMs = dependencies.eventPollMs ?? 1_000;
    const tail = new EventTail(database, userId, cursor);
    return streamSSE(context, async (stream) => {
      try {
        while (!subscriber.closed && !context.req.raw.signal.aborted) {
          subscriber.queue.length = 0;
          const events = await tail.next();
          for (const event of events) {
            await stream.writeSSE({
              id: String(event.id),
              event: event.event,
              data: JSON.stringify(event.data),
            });
          }
          if (events.length === EVENT_PAGE) continue;
          let onAbort: () => void = () => undefined;
          let timer: NodeJS.Timeout | undefined;
          await new Promise<void>((resolve) => {
            subscriber.wake = resolve;
            timer = setTimeout(resolve, pollMs);
            onAbort = () => resolve();
            context.req.raw.signal.addEventListener("abort", onAbort, { once: true });
          });
          clearTimeout(timer);
          context.req.raw.signal.removeEventListener("abort", onAbort);
          subscriber.wake = undefined;
        }
      } finally {
        subscriber.closed = true;
        group.delete(subscriber);
        if (!group.size) subscriptions.delete(userId);
      }
    });
  });

  app.get("/api/reports", async (context) => {
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
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
    const user = await requireUser(context, database, webAuth);
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

export type AgentMessageTask = {
  taskId: string;
  invocationId: string;
  runId?: string;
  userMessage: Awaited<ReturnType<typeof writeMessage>>;
};

/**
 * Write a user message as a new task, invocation and (when a ledger is present) durable
 * run, in the caller's transaction. Shared by the web route and the A2A gateway so both
 * produce exactly the rows the durable worker executes.
 */
export async function createAgentMessageTaskOnClient(
  client: PoolClient,
  input: {
    userId: string;
    spaceId: string;
    agent: string;
    content: string;
    runLedger?: RunLedger;
    idempotencyKey?: string;
  },
): Promise<AgentMessageTask> {
  const taskId = `t_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const invocationId = `inv_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const durable = Boolean(input.runLedger);
  await client.query(
    "INSERT INTO web_tasks (id, user_id, root_agent, status) VALUES ($1, $2, $3, 'running')",
    [taskId, input.userId, input.agent],
  );
  await client.query(
    `INSERT INTO web_invocations (id, task_id, user_id, agent, caller, inbound_text, status, started_at)
     VALUES ($1, $2, $3, $4, 'user', $5, $6, CASE WHEN $6 = 'running' THEN now() ELSE NULL END)`,
    [
      invocationId,
      taskId,
      input.userId,
      input.agent,
      input.content,
      durable ? "queued" : "running",
    ],
  );
  let runId: string | undefined;
  if (input.runLedger) {
    const created = await input.runLedger.createOnClient(client, {
      spaceId: input.spaceId,
      userId: input.userId,
      workflowId: "web.agent_message",
      workflowVersion: "1.0.0",
      idempotencyKey: input.idempotencyKey ?? `web-task:${taskId}`,
      input: { taskId, invocationId, agent: input.agent, content: input.content },
    });
    runId = created.id;
    await client.query("UPDATE web_tasks SET platform_run_id = $2 WHERE id = $1", [taskId, runId]);
    await client.query("UPDATE web_invocations SET platform_run_id = $2 WHERE id = $1", [
      invocationId,
      runId,
    ]);
  }
  const userMessage = await writeMessage(client, {
    userId: input.userId,
    agent: input.agent,
    taskId,
    invocationId,
    role: "user",
    content: input.content,
  });
  return { taskId, invocationId, runId, userMessage };
}

export async function reconcileInterruptedTasks(database: Pool): Promise<void> {
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `UPDATE web_invocations SET status = 'failed', error = 'API restarted while task was running',
         finished_at = COALESCE(finished_at, now())
       WHERE status = 'running' AND task_id IN
         (SELECT id FROM web_tasks WHERE status = 'running' AND platform_run_id IS NULL)`,
    );
    await client.query(
      `UPDATE web_tasks SET status = 'failed', finished_at = COALESCE(finished_at, now())
       WHERE status = 'running' AND platform_run_id IS NULL`,
    );
    await client.query(
      `UPDATE web_invocations SET status = 'failed', error = 'Invocation was left running',
         finished_at = COALESCE(finished_at, now())
       WHERE status = 'running' AND task_id IN
         (SELECT id FROM web_tasks WHERE platform_run_id IS NULL)`,
    );
    await client.query("COMMIT");
  } catch (failure) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw failure;
  } finally {
    client.release();
  }
}

export function createWebTaskRunExecutor(dependencies: {
  database: Pool;
  pluginRegistry: AgentPool;
  pool: McpToolPool;
  runtime: PiRuntime;
  catalog?: import("./planner.js").PlannerCatalog;
}) {
  return {
    async execute(run: ClaimedRun, signal: AbortSignal): Promise<unknown> {
      const input = parseWebTaskRunInput(run.input);
      const plugin = dependencies.pluginRegistry.get(input.agent);
      if (!plugin) throw new Error(`Unknown agent '${input.agent}' in durable run`);
      const controller = new AbortController();
      const abort = () => controller.abort(signal.reason);
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) abort();
      trackActiveTask(input.taskId, controller);
      try {
        await runTask({
          database: dependencies.database,
          plugin,
          pool: dependencies.pool,
          runtime: dependencies.runtime,
          catalog: dependencies.catalog ?? dependencies.pluginRegistry.plannerCatalog(),
          user: { id: run.user_id },
          agent: input.agent,
          taskId: input.taskId,
          invocationId: input.invocationId,
          content: input.content,
          spaceId: run.space_id,
          depth: input.depth,
          parentRunId: input.parentRunId,
          completeTask: input.completeTask,
          controller,
          trace: input.trace ? newTraceContext(input.trace) : newTraceContext(),
          durable: true,
          rethrowOnFailure: true,
        });
        return { task_id: input.taskId, invocation_id: input.invocationId };
      } finally {
        untrackActiveTask(input.taskId, controller);
        signal.removeEventListener("abort", abort);
      }
    },
  };
}

async function runTask(input: {
  database: Pool;
  plugin: AgentPlugin;
  pool: McpToolPool;
  runtime: PiRuntime;
  catalog?: import("./planner.js").PlannerCatalog;
  user: { id: string };
  agent: string;
  taskId: string;
  invocationId: string;
  content: string;
  spaceId?: string;
  depth?: number;
  parentRunId?: string;
  completeTask?: boolean;
  controller: AbortController;
  trace: TraceContext;
  durable?: boolean;
  rethrowOnFailure?: boolean;
}): Promise<void> {
  const {
    database,
    plugin,
    pool,
    runtime,
    catalog,
    user,
    agent,
    taskId,
    invocationId,
    content,
    spaceId = process.env.API_SPACE_ID ?? "local-space",
    depth = 0,
    parentRunId,
    completeTask = true,
    controller,
    trace,
    durable = false,
    rethrowOnFailure = false,
  } = input;
  controller.signal.throwIfAborted();
  await emit(database, user.id, "task.updated", { task: await getTask(database, taskId) });
  const started = await database.query(
    `UPDATE web_invocations SET status = 'running', started_at = COALESCE(started_at, now())
     WHERE id = $1 AND status = 'queued'`,
    [invocationId],
  );
  if (started.rowCount) {
    await emit(database, user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
  } else {
    const current = await database.query<{ status: string }>(
      "SELECT status FROM web_invocations WHERE id = $1",
      [invocationId],
    );
    if (current.rows[0]?.status === "cancelled") {
      controller.abort("task cancelled");
      controller.signal.throwIfAborted();
    }
  }
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
        spaceId,
        taskId,
        parentRunId,
        depth,
        signal: controller.signal,
        tools: pool.forNames(plugin.descriptor.tools),
        runtime,
        catalog,
        trace,
        pool,
        publish,
      }));
    if (plugin.descriptor.output && !Value.Check(plugin.descriptor.output, output)) {
      throw new Error("Agent output does not match its declared schema");
    }
    controller.signal.throwIfAborted();
    const taskState = await database.query<{ status: string }>(
      "SELECT status FROM web_tasks WHERE id = $1",
      [taskId],
    );
    if (taskState.rows[0]?.status === "cancelled") {
      controller.abort("task cancelled");
      controller.signal.throwIfAborted();
    }
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
    const finished = completeTask
      ? await database.query(
          `UPDATE web_tasks SET status = 'completed', finished_at = now()
           WHERE id = $1 AND status = 'running'
           RETURNING id, root_agent, status, created_at, finished_at`,
          [taskId],
        )
      : { rows: [] as Record<string, unknown>[] };
    await emit(database, user.id, "message.appended", { agent, message: messageDto(saved) });
    await emit(database, user.id, "invocation.updated", {
      invocation: await getInvocation(database, invocationId),
    });
    if (finished.rows[0])
      await emit(database, user.id, "task.updated", { task: taskDto(finished.rows[0]) });
  } catch (failure) {
    const cancelled = isCancellationReason(controller.signal.reason);
    const leaseAbort = durable && controller.signal.aborted && !cancelled;
    const reason =
      failure instanceof Error ? failure.message : String(failure || "Agent run failed");
    if (!leaseAbort) {
      await database.query(
        `UPDATE web_invocations SET status = $2, error = $3, finished_at = now() WHERE id = $1`,
        [invocationId, cancelled ? "cancelled" : "failed", reason],
      );
      const finished = completeTask
        ? await database.query(
            `UPDATE web_tasks SET status = $2, finished_at = now()
             WHERE id = $1 AND status = 'running'
             RETURNING id, root_agent, status, created_at, finished_at`,
            [taskId, cancelled ? "cancelled" : "failed"],
          )
        : { rows: [] as Record<string, unknown>[] };
      await emit(database, user.id, "invocation.updated", {
        invocation: await getInvocation(database, invocationId),
      });
      if (finished.rows[0])
        await emit(database, user.id, "task.updated", { task: taskDto(finished.rows[0]) });
    }
    if (rethrowOnFailure) throw failure;
  } finally {
    untrackActiveTask(taskId, controller);
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

async function authenticateUser(
  context: Context,
  database: Pool,
  config?: WebAuthConfig,
): Promise<{ id: string; name: string } | undefined> {
  const session = verifyWebSession(
    bearerToken(context.req.header("authorization")),
    config ?? { mode: "demo", ttlSeconds: 0 },
  );
  const userId =
    session?.userId ?? (config?.mode === "session" ? undefined : context.req.header("x-user-id"));
  if (!userId) return undefined;
  const result = await database.query("SELECT id, name FROM web_users WHERE id = $1", [userId]);
  return result.rows[0] as { id: string; name: string } | undefined;
}

async function requireUser(context: Context, database: Pool, config?: WebAuthConfig) {
  return authenticateUser(context, database, config);
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
    `SELECT id, task_id, agent, caller, parent_id, tool_call_id,
      depth, inbound_text, status, result_text, error, created_at, started_at, finished_at,
      platform_run_id
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

/** Wake local subscribers; the event itself is read back from `web_events`. */
function publish(userId: string, event: string, data: Record<string, unknown>, id?: number) {
  for (const subscriber of subscriptions.get(userId) ?? []) {
    subscriber.queue.push({ id, event, data });
    subscriber.wake?.();
  }
}

const EVENT_PAGE = 500;
/** Rows committed out of id order stay visible to the tail for this long. */
const EVENT_LATE_WINDOW_MS = 2_000;

/**
 * Reads `web_events` after a cursor. Two concurrent inserts can commit in the opposite
 * order to their ids, so a plain `id > cursor` read could step past a row that becomes
 * visible a moment later. The tail re-reads a short recent window and drops ids it has
 * already sent, so a late row is still delivered, once.
 */
export class EventTail {
  private cursor: number;
  /** The client's resume point: nothing at or below it is ever re-sent. */
  private readonly floor: number;
  private readonly sent = new Set<number>();

  constructor(
    private readonly database: Pick<Pool, "query">,
    private readonly userId: string,
    after: number,
  ) {
    this.cursor = after;
    this.floor = after;
  }

  async next(): Promise<Array<{ id: number; event: string; data: Record<string, unknown> }>> {
    const result = await this.database.query<{
      id: string;
      event: string;
      data: Record<string, unknown>;
    }>(
      `SELECT id, event, data FROM web_events
       WHERE user_id = $1
         AND (id > $2 OR (id > $3 AND created_at > now() - ($4 * interval '1 millisecond')))
       ORDER BY id ASC LIMIT $5`,
      [this.userId, this.cursor, this.floor, EVENT_LATE_WINDOW_MS, EVENT_PAGE],
    );
    const fresh = result.rows
      .map((row) => ({ id: Number(row.id), event: row.event, data: row.data }))
      .filter((row) => !this.sent.has(row.id));
    for (const row of fresh) {
      this.sent.add(row.id);
      if (row.id > this.cursor) this.cursor = row.id;
    }
    this.prune();
    return fresh;
  }

  private prune(): void {
    if (this.sent.size <= 4 * EVENT_PAGE) return;
    const keep = [...this.sent].sort((left, right) => right - left).slice(0, 2 * EVENT_PAGE);
    this.sent.clear();
    for (const id of keep) this.sent.add(id);
  }
}

async function emit(
  database: Pool,
  userId: string,
  event: string,
  data: Record<string, unknown>,
): Promise<void> {
  try {
    const result = await database.query<{ id: string }>(
      `INSERT INTO web_events (user_id, event, data)
       VALUES ($1, $2, $3::jsonb) RETURNING id`,
      [userId, event, JSON.stringify(data)],
    );
    publish(userId, event, data, Number(result.rows[0]?.id));
  } catch (error) {
    // A task may finish after its user has been deleted. The FK rejection is a
    // terminal no-op for the event projection; never turn it into an unhandled
    // worker rejection or recreate deleted tenant data.
    if (isPgForeignKeyViolation(error)) return;
    throw error;
  }
}

function isPgForeignKeyViolation(error: unknown): boolean {
  return isRecord(error) && error.code === "23503";
}

function isCancellationReason(reason: unknown): boolean {
  return (
    reason === "task cancelled" ||
    (reason instanceof Error &&
      (reason.name === "RunCancelledError" || reason.message === "Run cancelled"))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTraceContext(value: unknown): value is TraceContext {
  return (
    isRecord(value) &&
    typeof value.traceId === "string" &&
    typeof value.spanId === "string" &&
    (value.parentSpanId === undefined || typeof value.parentSpanId === "string")
  );
}

function parseCursor(value: string | undefined): number | undefined {
  if (value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

function parseWebTaskRunInput(value: unknown): {
  taskId: string;
  invocationId: string;
  agent: string;
  content: string;
  depth: number;
  parentRunId?: string;
  trace?: TraceContext;
  completeTask: boolean;
} {
  if (
    !isRecord(value) ||
    typeof value.taskId !== "string" ||
    typeof value.invocationId !== "string" ||
    typeof value.agent !== "string" ||
    typeof value.content !== "string"
  ) {
    throw new Error("Durable web task input is invalid");
  }
  return {
    taskId: value.taskId,
    invocationId: value.invocationId,
    agent: value.agent,
    content: value.content,
    depth:
      typeof value.depth === "number" && Number.isInteger(value.depth) && value.depth >= 0
        ? value.depth
        : 0,
    parentRunId:
      typeof value.parentInvocationId === "string" ? value.parentInvocationId : undefined,
    trace: isTraceContext(value.trace) ? value.trace : undefined,
    completeTask: value.completeTask !== false,
  };
}

function error(context: Context, status: number, code: string, message: string) {
  return context.json({ error: { code, message } }, status as ContentfulStatusCode);
}
