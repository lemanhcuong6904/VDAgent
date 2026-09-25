import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import { Type } from "typebox";
import type { PiRuntime } from "../pi-runtime.js";
import type { AgentPool } from "../registry.js";
import type { McpPoolTool, McpToolPool, ToolScope } from "../tool-pool.js";

const SPECIALISTS = ["data", "compare", "insight", "visualize", "report"] as const;
const MAX_DELEGATIONS_PER_TASK = 5;
export function createAgentDelegationTool(dependencies: {
  database: Pool;
  pluginRegistry: AgentPool;
  pool: McpToolPool;
  runtime: PiRuntime;
}): McpPoolTool {
  return {
    name: "agents.delegate",
    description: "Ask one specialist agent to complete a focused task and return its result.",
    schema: Type.Object({
      agent: Type.Union(SPECIALISTS.map((id) => Type.Literal(id))),
      message: Type.String({ minLength: 1, maxLength: 4000 }),
    }),
    mutates: true,
    agents: ["orchestrator"],
    authorize: (scope) => scope.agentId === "orchestrator",
    async execute(raw, scope) {
      const value = raw as { agent: (typeof SPECIALISTS)[number]; message: string };
      return delegate(value, scope, dependencies);
    },
  };
}

async function delegate(
  input: { agent: (typeof SPECIALISTS)[number]; message: string },
  scope: ToolScope,
  dependencies: {
    database: Pool;
    pluginRegistry: AgentPool;
    pool: McpToolPool;
    runtime: PiRuntime;
  },
): Promise<string> {
  const { database, pluginRegistry, pool, runtime } = dependencies;
  if (scope.agentId !== "orchestrator" || scope.depth !== 0 || !scope.taskId || !scope.runId) {
    throw new Error("Agent delegation is only available to a running orchestrator task");
  }
  const callCount = await database.query<{ count: string }>(
    "SELECT count(*)::text AS count FROM web_invocations WHERE task_id = $1 AND depth > 0",
    [scope.taskId],
  );
  if (Number(callCount.rows[0]?.count ?? 0) >= MAX_DELEGATIONS_PER_TASK) {
    throw new Error("This task has reached its specialist-call limit");
  }

  const parent = await database.query<{ task_id: string; user_id: string; depth: number }>(
    `SELECT task_id, user_id, depth FROM web_invocations
     WHERE id = $1 AND agent = 'orchestrator' AND status = 'running'`,
    [scope.runId],
  );
  const parentInvocation = parent.rows[0];
  if (!parentInvocation || parentInvocation.task_id !== scope.taskId) {
    throw new Error("The parent invocation is unavailable");
  }
  const plugin = pluginRegistry.get(input.agent);
  if (!plugin) throw new Error(`Specialist '${input.agent}' is unavailable`);

  const invocationId = `inv_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO web_invocations
       (id, task_id, user_id, agent, caller, parent_id, tool_call_id, depth, inbound_text, status, started_at)
       VALUES ($1, $2, $3, $4, 'orchestrator', $5, $6, 1, $7, 'running', now())`,
      [
        invocationId,
        scope.taskId,
        scope.userId,
        input.agent,
        scope.runId,
        scope.toolCallId ?? null,
        input.message,
      ],
    );
    const inbound = await insertMessage(client, {
      userId: scope.userId,
      agent: input.agent,
      taskId: scope.taskId,
      invocationId,
      role: "user",
      sender: "orchestrator",
      content: input.message,
    });
    await client.query("COMMIT");
    scope.publish?.(scope.userId, "message.appended", {
      agent: input.agent,
      message: messageDto(inbound),
    });
  } catch (failure) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw failure;
  } finally {
    client.release();
  }
  await publishInvocation(database, scope, invocationId);

  try {
    const output = await plugin.run(
      { prompt: input.message },
      {
        runId: invocationId,
        sessionId: `web:${scope.userId}:${input.agent}`,
        userId: scope.userId,
        spaceId: scope.spaceId,
        signal: scope.signal,
        tools: pool.forNames(plugin.descriptor.tools),
        runtime,
        pool,
        taskId: scope.taskId,
        depth: 1,
        publish: scope.publish,
      },
    );
    const resultText = await includeCreatedArtifacts(
      database,
      scope.userId,
      invocationId,
      input.agent,
      renderOutput(output),
    );
    const saved = await insertOutputMessage(database, {
      userId: scope.userId,
      agent: input.agent,
      taskId: scope.taskId,
      invocationId,
      content: resultText,
    });
    await database.query(
      `UPDATE web_invocations SET status = 'completed', result_text = $2, finished_at = now()
       WHERE id = $1`,
      [invocationId, resultText],
    );
    scope.publish?.(scope.userId, "message.appended", {
      agent: input.agent,
      message: messageDto(saved),
    });
    await publishInvocation(database, scope, invocationId);
    return resultText;
  } catch (failure) {
    const detail = failure instanceof Error ? failure.message : "Agent delegation failed";
    const result = `error: ${detail}`;
    await database.query(
      `UPDATE web_invocations SET status = 'failed', error = $2, result_text = $2, finished_at = now()
       WHERE id = $1`,
      [invocationId, detail],
    );
    await publishInvocation(database, scope, invocationId);
    return result;
  }
}

async function insertOutputMessage(
  database: Pool,
  input: { userId: string; agent: string; taskId: string; invocationId: string; content: string },
) {
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    const message = await insertMessage(client, { ...input, role: "assistant", sender: null });
    await client.query("COMMIT");
    return message;
  } catch (failure) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw failure;
  } finally {
    client.release();
  }
}

async function insertMessage(
  client: PoolClient,
  input: {
    userId: string;
    agent: string;
    taskId: string;
    invocationId: string;
    role: "user" | "assistant";
    sender: string | null;
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
  const result = await client.query(
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
      input.sender,
      input.content,
    ],
  );
  return result.rows[0];
}

async function publishInvocation(database: Pool, scope: ToolScope, id: string) {
  const result = await database.query(
    `SELECT id, task_id, agent, caller, parent_id, tool_call_id, depth, inbound_text, status,
      result_text, error, created_at, started_at, finished_at
     FROM web_invocations WHERE id = $1`,
    [id],
  );
  const invocation = result.rows[0];
  if (invocation) scope.publish?.(scope.userId, "invocation.updated", { invocation });
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

function renderOutput(output: unknown): string {
  if (typeof output === "string") return output;
  return JSON.stringify(output, null, 2);
}

async function includeCreatedArtifacts(
  database: Pool,
  userId: string,
  invocationId: string,
  agent: string,
  result: string,
): Promise<string> {
  if (agent === "visualize") {
    const charts = await database.query<{ id: string }>(
      "SELECT id FROM web_charts WHERE user_id = $1 AND invocation_id = $2",
      [userId, invocationId],
    );
    const missing = charts.rows.map(({ id }) => id).filter((id) => !result.includes(id));
    return missing.length ? `${result}\n\nCreated charts: ${missing.join(", ")}` : result;
  }
  if (agent !== "report") return result;
  const artifacts = await database.query<{ id: string }>(
    `SELECT id FROM web_datasets WHERE user_id = $1 AND invocation_id = $2
     UNION ALL
     SELECT id FROM web_charts WHERE user_id = $1 AND invocation_id = $2
     UNION ALL
     SELECT id FROM web_reports WHERE user_id = $1 AND invocation_id = $2`,
    [userId, invocationId],
  );
  const ids = [...new Set(artifacts.rows.map(({ id }) => id))];
  const missing = ids.filter((id) => !result.includes(id));
  return missing.length ? `${result}\n\nCreated artifacts: ${missing.join(", ")}` : result;
}
