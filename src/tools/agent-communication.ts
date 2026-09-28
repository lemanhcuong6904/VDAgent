import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import { Type } from "typebox";
import { Value } from "typebox/value";
import type { AgentPlugin } from "../agent-contract.js";
import type { AgentPool } from "../registry.js";
import type { RunLedger } from "../run-ledger.js";
import type { RunStatus } from "../run-state.js";
import type { McpPoolTool, ToolScope } from "../tool-pool.js";

const MAX_MESSAGE_BYTES = 16_000;
const MAX_FANOUT_PER_PARENT = 8;
const MAX_CHILDREN_PER_TASK = 32;
const MAX_DEPTH = 8;
const DEFAULT_WAIT_MS = 30_000;
const MAX_WAIT_MS = 60_000;
const DEFAULT_ASK_WAIT_MS = 30_000;

type SendInput = {
  agent?: string;
  to?: string;
  capability?: string;
  message: string;
  idempotencyKey?: string;
};

type AskInput = {
  agent: string;
  question: string;
  questionId?: string;
  timeoutMs?: number;
};

type AnswerInput = {
  questionId: string;
  output?: unknown;
  error?: string;
};

type CommunicationDependencies = {
  database: Pool;
  runLedger: RunLedger;
  pluginRegistry: AgentPool;
  allowedEdges?: ReadonlyMap<string, ReadonlySet<string>>;
};

/** Durable, policy-checked agent-to-agent communication ports. */
export function createAgentCommunicationTools(
  dependencies: CommunicationDependencies,
): McpPoolTool[] {
  return [
    {
      name: "agents.send",
      description:
        "Queue a durable message for another registered agent in the current task and return its run receipt.",
      schema: Type.Object({
        agent: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
        to: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
        capability: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
        message: Type.String({ minLength: 1, maxLength: 4_000 }),
        idempotencyKey: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      }),
      mutates: true,
      agents: ["*"],
      authorize: (scope) => isInvocationScope(scope),
      async execute(raw, scope) {
        return sendMessage(raw as SendInput, scope, dependencies);
      },
    },
    {
      name: "agents.wait",
      description: "Wait for a child agent run that belongs to the current task.",
      schema: Type.Object({
        runId: Type.String({ minLength: 1, maxLength: 128 }),
        timeoutMs: Type.Optional(Type.Integer({ minimum: 0, maximum: MAX_WAIT_MS })),
      }),
      mutates: false,
      agents: ["*"],
      authorize: (scope) => isInvocationScope(scope),
      async execute(raw, scope) {
        const value = raw as { runId: string; timeoutMs?: number };
        return waitForRun(value.runId, value.timeoutMs ?? DEFAULT_WAIT_MS, scope, dependencies);
      },
    },
    {
      name: "agents.result",
      description: "Read the durable status, result, and error of a child agent run.",
      schema: Type.Object({ runId: Type.String({ minLength: 1, maxLength: 128 }) }),
      mutates: false,
      agents: ["*"],
      authorize: (scope) => isInvocationScope(scope),
      async execute(raw, scope) {
        const value = raw as { runId: string };
        return readRunResult(value.runId, scope, dependencies);
      },
    },
    {
      name: "agents.ask",
      description:
        "Ask a peer agent in the same task a question and block for its answer. Unlike agents.send, the " +
        "target does not have to be a descendant: any agent running in the same task may be asked, " +
        "provided doing so would not create a wait-for cycle.",
      schema: Type.Object({
        agent: Type.String({ minLength: 1, maxLength: 128 }),
        question: Type.String({ minLength: 1, maxLength: 4_000 }),
        questionId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
        timeoutMs: Type.Optional(Type.Integer({ minimum: 0, maximum: MAX_WAIT_MS })),
      }),
      mutates: true,
      agents: ["*"],
      authorize: (scope) => isInvocationScope(scope),
      async execute(raw, scope) {
        return askPeer(raw as AskInput, scope, dependencies);
      },
    },
    {
      name: "agents.answer",
      description:
        "Answer a pending question from a peer agent, waking it if it is blocked on agents.ask.",
      schema: Type.Object({
        questionId: Type.String({ minLength: 1, maxLength: 128 }),
        output: Type.Optional(Type.Unknown()),
        error: Type.Optional(Type.String({ minLength: 1, maxLength: 4_000 })),
      }),
      mutates: true,
      agents: ["*"],
      authorize: (scope) => isInvocationScope(scope),
      async execute(raw, scope) {
        return answerPeer(raw as AnswerInput, scope, dependencies);
      },
    },
  ];
}

async function sendMessage(
  input: SendInput,
  scope: ToolScope,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> {
  if (!isInvocationScope(scope)) {
    throw new Error("Agent messaging is only available to a running agent invocation");
  }
  const sender = scope.agentId;
  if (!sender) throw new Error("Agent identity is required for messaging");
  const taskId = scope.taskId;
  if (!taskId) throw new Error("Task identity is required for messaging");
  const senderPlugin = dependencies.pluginRegistry.get(sender);
  if (!senderPlugin) throw new Error(`Unknown sender agent '${sender}'`);
  if (Buffer.byteLength(input.message, "utf8") > MAX_MESSAGE_BYTES) {
    throw new Error("Agent message is too large");
  }
  const targetId = input.agent ?? input.to;
  if (input.agent && input.to && input.agent !== input.to) {
    throw new Error("Specify one target agent");
  }
  if (!targetId && !input.capability) {
    throw new Error("Specify an agent or capability");
  }
  if (targetId && input.capability) {
    throw new Error("Specify an agent or capability, not both");
  }

  const target = resolveTarget(targetId, input.capability, sender, dependencies.pluginRegistry);
  if (target.descriptor.id === sender) {
    throw new Error("An agent cannot send a message to itself");
  }
  if (!Value.Check(target.descriptor.input, { prompt: input.message })) {
    throw new Error(`Agent '${target.descriptor.id}' does not accept a prompt message`);
  }
  if (!isEdgeAllowed(sender, target.descriptor.id, dependencies.allowedEdges)) {
    throw new Error(`Agent '${sender}' is not allowed to message '${target.descriptor.id}'`);
  }

  const client = await dependencies.database.connect();
  try {
    await client.query("BEGIN");
    const parent = await client.query<{
      id: string;
      task_id: string;
      user_id: string;
      depth: number;
      status: string;
      agent: string;
      platform_run_id: string | null;
      space_id: string;
    }>(
      `SELECT i.id, i.task_id, i.user_id, i.depth, i.status, i.agent, i.platform_run_id,
              p.space_id
       FROM web_invocations i
       JOIN platform_runs p ON p.id = i.platform_run_id
       WHERE i.id = $1 AND i.task_id = $2 AND i.user_id = $3 AND p.space_id = $4
       FOR UPDATE`,
      [scope.runId, scope.taskId, scope.userId, scope.spaceId],
    );
    const parentRow = parent.rows[0];
    if (!parentRow || parentRow.agent !== sender || parentRow.status !== "running") {
      throw new Error("The parent invocation is unavailable for agent messaging");
    }
    const childDepth = Number(parentRow.depth) + 1;
    const maxDepth = Math.min(MAX_DEPTH, senderPlugin.descriptor.limits?.maxDepth ?? MAX_DEPTH);
    if (childDepth > maxDepth) throw new Error("This task has reached its agent depth limit");

    const requestKey = input.idempotencyKey ?? scope.toolCallId;
    const idempotencyKey = `a2a:${scope.runId}:${requestKey ?? randomUUID()}`.slice(0, 256);
    const existing = await client.query<ExistingReceipt>(
      `SELECT p.id AS run_id, p.status AS run_status, i.id AS invocation_id,
              i.agent, i.task_id
       FROM platform_runs p
       JOIN web_invocations i ON i.platform_run_id = p.id
       WHERE p.space_id = $1 AND p.user_id = $2 AND p.idempotency_key = $3
       FOR UPDATE`,
      [scope.spaceId, scope.userId, idempotencyKey],
    );
    if (existing.rows[0]) {
      await client.query("COMMIT");
      return receipt(existing.rows[0]);
    }

    const fanout = await client.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM web_invocations
       WHERE parent_id = $1 AND status <> 'rejected'`,
      [scope.runId],
    );
    const maxFanout = Math.min(
      MAX_FANOUT_PER_PARENT,
      senderPlugin.descriptor.limits?.maxParallelChildren ?? MAX_FANOUT_PER_PARENT,
    );
    if (Number(fanout.rows[0]?.count ?? 0) >= maxFanout) {
      throw new Error("This agent has reached its child-run fan-out limit");
    }
    const taskChildren = await client.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM web_invocations
       WHERE task_id = $1 AND depth > 0 AND status <> 'rejected'`,
      [taskId],
    );
    if (Number(taskChildren.rows[0]?.count ?? 0) >= MAX_CHILDREN_PER_TASK) {
      throw new Error("This task has reached its child-run limit");
    }

    const invocationId = `inv_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
    const created = await dependencies.runLedger.createOnClient(client, {
      spaceId: scope.spaceId,
      userId: scope.userId,
      workflowId: "agent.message",
      workflowVersion: "1.0.0",
      idempotencyKey,
      input: {
        taskId,
        invocationId,
        agent: target.descriptor.id,
        content: input.message,
        depth: childDepth,
        parentInvocationId: scope.runId,
        trace: scope.trace,
        completeTask: false,
      },
    });
    await client.query(
      `INSERT INTO web_invocations
       (id, task_id, user_id, agent, caller, parent_id, tool_call_id, depth, inbound_text, status,
        platform_run_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'queued', $10)`,
      [
        invocationId,
        taskId,
        scope.userId,
        target.descriptor.id,
        sender,
        scope.runId,
        scope.toolCallId ?? null,
        childDepth,
        input.message,
        created.id,
      ],
    );
    const message = await insertMessage(client, {
      userId: scope.userId,
      agent: target.descriptor.id,
      taskId,
      invocationId,
      role: "user",
      sender,
      content: input.message,
    });
    await client.query("COMMIT");
    scope.publish?.(scope.userId, "message.appended", {
      agent: target.descriptor.id,
      message: messageDto(message),
    });
    scope.publish?.(scope.userId, "invocation.updated", {
      invocation: await getInvocation(dependencies.database, invocationId),
    });
    return {
      runId: created.id,
      invocationId,
      taskId,
      agent: target.descriptor.id,
      status: created.status,
      depth: childDepth,
    };
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function askPeer(
  input: AskInput,
  scope: ToolScope,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> {
  if (!isInvocationScope(scope)) {
    throw new Error("Agent messaging is only available to a running agent invocation");
  }
  const sender = scope.agentId;
  if (!sender) throw new Error("Agent identity is required for messaging");
  const taskId = scope.taskId;
  if (!taskId) throw new Error("Task identity is required for messaging");
  if (input.agent === sender) throw new Error("An agent cannot ask itself a question");
  if (Buffer.byteLength(input.question, "utf8") > MAX_MESSAGE_BYTES) {
    throw new Error("Agent question is too large");
  }
  const targetPlugin = dependencies.pluginRegistry.get(input.agent);
  if (!targetPlugin) throw new Error(`Unknown target agent '${input.agent}'`);
  if (!isEdgeAllowed(sender, input.agent, dependencies.allowedEdges)) {
    throw new Error(`Agent '${sender}' is not allowed to ask '${input.agent}'`);
  }

  const questionId = input.questionId ?? `q_${randomUUID().replaceAll("-", "").slice(0, 16)}`;
  const askId = `ask_${randomUUID().replaceAll("-", "").slice(0, 16)}`;
  const timeoutMs = Math.min(MAX_WAIT_MS, Math.max(0, input.timeoutMs ?? DEFAULT_ASK_WAIT_MS));

  const client = await dependencies.database.connect();
  try {
    await client.query("BEGIN");
    // Serialize wait-for-graph mutation per task so concurrent asks cannot
    // race past each other and both pass the cycle check.
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
      `wait-for:${taskId}`,
    ]);

    const existing = await client.query<ExistingAsk>(
      `SELECT id, task_id, user_id, space_id, question_id, from_agent, to_agent, content,
              status, answer, answer_status FROM web_agent_asks
       WHERE task_id = $1 AND question_id = $2`,
      [taskId, questionId],
    );
    if (existing.rows[0]) {
      const previous = existing.rows[0];
      if (
        previous.task_id !== taskId ||
        previous.user_id !== scope.userId ||
        previous.space_id !== scope.spaceId ||
        previous.from_agent !== sender ||
        previous.to_agent !== input.agent ||
        getQuestionText(previous.content) !== input.question
      ) {
        throw new Error("question_id_conflict: questionId was already used for a different ask");
      }
      await client.query("ROLLBACK");
      return askOutcome(
        previous,
        sender,
        input.agent,
        taskId,
        timeoutMs,
        scope.signal,
        dependencies,
      );
    }

    if (await wouldCreateWaitForCycle(client, taskId, sender, input.agent)) {
      throw new Error(
        `Asking '${input.agent}' would create a wait-for cycle with '${sender}' in this task`,
      );
    }

    await client.query(
      `INSERT INTO web_agent_asks
       (id, task_id, user_id, space_id, question_id, from_agent, to_agent, content, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending')`,
      [
        askId,
        taskId,
        scope.userId,
        scope.spaceId,
        questionId,
        sender,
        input.agent,
        JSON.stringify({ question: input.question }),
      ],
    );
    await client.query(
      `INSERT INTO web_wait_for_edges (task_id, question_id, waiting_agent, blocked_on_agent)
       VALUES ($1, $2, $3, $4)`,
      [taskId, questionId, sender, input.agent],
    );
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }

  scope.publish?.(scope.userId, "agent.asked", {
    taskId,
    questionId,
    from: sender,
    to: input.agent,
  });
  return pollForAnswer(
    dependencies,
    taskId,
    questionId,
    sender,
    input.agent,
    timeoutMs,
    scope.signal,
  );
}

async function answerPeer(
  input: AnswerInput,
  scope: ToolScope,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> {
  if (!isInvocationScope(scope)) {
    throw new Error("Agent messaging is only available to a running agent invocation");
  }
  const responder = scope.agentId;
  if (!responder) throw new Error("Agent identity is required for messaging");
  const taskId = scope.taskId;
  if (!taskId) throw new Error("Task identity is required for messaging");

  const client = await dependencies.database.connect();
  try {
    await client.query("BEGIN");
    const row = await client.query<{ id: string; to_agent: string; status: string }>(
      `SELECT id, to_agent, status FROM web_agent_asks
       WHERE task_id = $1 AND question_id = $2 FOR UPDATE`,
      [taskId, input.questionId],
    );
    const ask = row.rows[0];
    if (!ask) throw new Error("Question not found in the current task");
    if (ask.to_agent !== responder)
      throw new Error("Only the asked agent may answer this question");
    if (ask.status !== "pending") {
      await client.query("COMMIT");
      return { questionId: input.questionId, delivered: false, reason: "already answered" };
    }

    const answerStatus = input.error ? "error" : "success";
    await client.query(
      `UPDATE web_agent_asks
       SET status = 'answered', answer = $1, answer_status = $2, answered_at = now()
       WHERE task_id = $3 AND question_id = $4`,
      [
        JSON.stringify(input.error ? { error: input.error } : { output: input.output ?? null }),
        answerStatus,
        taskId,
        input.questionId,
      ],
    );
    await client.query(`DELETE FROM web_wait_for_edges WHERE task_id = $1 AND question_id = $2`, [
      taskId,
      input.questionId,
    ]);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }

  scope.publish?.(scope.userId, "agent.answered", {
    taskId,
    questionId: input.questionId,
    by: responder,
  });
  return { questionId: input.questionId, delivered: true };
}

/**
 * Depth-first search over the current per-task wait-for graph plus the
 * candidate edge (waitingAgent -> blockedOnAgent). Mirrors
 * InMemoryMailbox.wouldCreateCycle, but reads the durable, per-task edge set
 * instead of an in-memory map.
 */
async function wouldCreateWaitForCycle(
  client: PoolClient,
  taskId: string,
  waitingAgent: string,
  blockedOnAgent: string,
): Promise<boolean> {
  const edges = await client.query<{ waiting_agent: string; blocked_on_agent: string }>(
    `SELECT waiting_agent, blocked_on_agent FROM web_wait_for_edges WHERE task_id = $1`,
    [taskId],
  );
  const adjacency = new Map<string, string[]>();
  for (const edge of edges.rows) {
    const targets = adjacency.get(edge.waiting_agent) ?? [];
    targets.push(edge.blocked_on_agent);
    adjacency.set(edge.waiting_agent, targets);
  }
  const candidateTargets = adjacency.get(waitingAgent) ?? [];
  adjacency.set(waitingAgent, [...candidateTargets, blockedOnAgent]);

  const visited = new Set<string>();
  const stack = [waitingAgent];
  while (stack.length > 0) {
    const current = stack.pop();
    if (current === undefined) break;
    if (current === waitingAgent && visited.size > 0) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    for (const next of adjacency.get(current) ?? []) {
      if (next === waitingAgent) return true;
      stack.push(next);
    }
  }
  return false;
}

function askOutcome(
  row: ExistingAsk,
  from: string,
  to: string,
  taskId: string,
  timeoutMs: number,
  signal: AbortSignal,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> | Record<string, unknown> {
  if (row.status === "answered") {
    return {
      questionId: row.question_id,
      from,
      to,
      status: row.answer_status,
      output: (row.answer as { output?: unknown } | null)?.output ?? null,
      error: (row.answer as { error?: string } | null)?.error ?? null,
      terminal: true,
    };
  }
  return pollForAnswer(dependencies, taskId, row.question_id, from, to, timeoutMs, signal);
}

async function pollForAnswer(
  dependencies: CommunicationDependencies,
  taskId: string,
  questionId: string,
  from: string,
  to: string,
  timeoutMs: number,
  signal: AbortSignal,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const result = await dependencies.database.query<{
      status: string;
      answer: unknown;
      answer_status: string | null;
    }>(
      `SELECT status, answer, answer_status FROM web_agent_asks WHERE task_id = $1 AND question_id = $2`,
      [taskId, questionId],
    );
    const row = result.rows[0];
    if (!row) throw new Error("Question not found in the current task");
    if (row.status === "answered") {
      return {
        questionId,
        from,
        to,
        status: row.answer_status,
        output: (row.answer as { output?: unknown } | null)?.output ?? null,
        error: (row.answer as { error?: string } | null)?.error ?? null,
        terminal: true,
      };
    }
    if (Date.now() >= deadline) {
      return {
        questionId,
        from,
        to,
        status: "timeout",
        output: null,
        error: null,
        terminal: false,
      };
    }
    const remaining = Math.min(100, deadline - Date.now());
    await delayWithSignal(Math.max(1, remaining), signal);
  }
}

type ExistingReceipt = {
  run_id: string;
  run_status: RunStatus;
  invocation_id: string;
  agent: string;
  task_id: string;
};

type ExistingAsk = {
  id: string;
  task_id: string;
  user_id: string;
  space_id: string;
  question_id: string;
  from_agent: string;
  to_agent: string;
  content: unknown;
  status: string;
  answer: unknown;
  answer_status: string | null;
};

function getQuestionText(content: unknown): string | undefined {
  let value = content;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return undefined;
    }
  }
  if (!isRecord(value)) return undefined;
  return typeof value.question === "string" ? value.question : undefined;
}

function receipt(value: ExistingReceipt): Record<string, unknown> {
  return {
    runId: value.run_id,
    invocationId: value.invocation_id,
    taskId: value.task_id,
    agent: value.agent,
    status: value.run_status,
    deduplicated: true,
  };
}

async function waitForRun(
  runId: string,
  timeoutMs: number,
  scope: ToolScope,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + Math.min(MAX_WAIT_MS, Math.max(0, timeoutMs));
  while (true) {
    const result = await readRunResult(runId, scope, dependencies);
    if (result.terminal || Date.now() >= deadline) return result;
    const remaining = Math.min(100, deadline - Date.now());
    await delayWithSignal(Math.max(1, remaining), scope.signal);
  }
}

async function readRunResult(
  runId: string,
  scope: ToolScope,
  dependencies: CommunicationDependencies,
): Promise<Record<string, unknown>> {
  if (!isInvocationScope(scope)) {
    throw new Error("Agent results are only available to a running agent invocation");
  }
  const result = await dependencies.database.query<RunResultRow>(
    `SELECT p.id AS run_id, p.status AS run_status, p.output AS run_output, p.error AS run_error,
            p.created_at, p.finished_at, i.id AS invocation_id, i.agent,
            i.status AS invocation_status, i.result_text, i.error AS invocation_error
     FROM platform_runs p
     JOIN web_invocations i ON i.platform_run_id = p.id
     WHERE p.id = $1 AND p.space_id = $2 AND p.user_id = $3 AND i.task_id = $4
       AND i.parent_id = $5`,
    [runId, scope.spaceId, scope.userId, scope.taskId, scope.runId],
  );
  const row = result.rows[0];
  if (!row) throw new Error("Agent run not found in the current scope");
  const terminal = isTerminal(row.run_status);
  return {
    runId: row.run_id,
    invocationId: row.invocation_id,
    taskId: scope.taskId,
    agent: row.agent,
    status: row.run_status,
    invocationStatus: row.invocation_status,
    terminal,
    output: row.result_text !== null ? decodeResult(row.result_text) : (row.run_output ?? null),
    error: row.invocation_error ?? row.run_error ?? null,
    createdAt: asIso(row.created_at),
    finishedAt: row.finished_at ? asIso(row.finished_at) : null,
  };
}

type RunResultRow = {
  run_id: string;
  run_status: RunStatus;
  run_output: unknown;
  run_error: string | null;
  created_at: string | Date;
  finished_at: string | Date | null;
  invocation_id: string;
  agent: string;
  invocation_status: string;
  result_text: string | null;
  invocation_error: string | null;
};

function resolveTarget(
  agentId: string | undefined,
  capability: string | undefined,
  sender: string,
  registry: AgentPool,
): AgentPlugin {
  if (agentId) {
    const plugin = registry.get(agentId);
    if (!plugin?.descriptor.acceptsDelegation) {
      throw new Error(`Agent '${agentId}' is unavailable for messaging`);
    }
    return plugin;
  }
  const candidates = registry
    .findByCapability(capability ?? "")
    .filter(({ descriptor }) => descriptor.id !== sender && descriptor.acceptsDelegation);
  const plugin = candidates[0];
  if (!plugin) throw new Error(`No delegatable agent provides '${capability}'`);
  return plugin;
}

function isEdgeAllowed(
  sender: string,
  target: string,
  configured?: ReadonlyMap<string, ReadonlySet<string>>,
): boolean {
  const edges = configured ?? parseEdges(process.env.AGENT_A2A_ALLOWED_EDGES);
  if (!edges) return true;
  const allowed = edges.get(sender) ?? edges.get("*");
  return Boolean(allowed?.has(target) || allowed?.has("*"));
}

function parseEdges(raw: string | undefined): ReadonlyMap<string, ReadonlySet<string>> | undefined {
  if (!raw?.trim()) return undefined;
  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value)) throw new Error("edges must be an object");
    const result = new Map<string, ReadonlySet<string>>();
    for (const [sender, targets] of Object.entries(value)) {
      if (!Array.isArray(targets) || !targets.every((target) => typeof target === "string")) {
        throw new Error("edge targets must be string arrays");
      }
      result.set(sender, new Set(targets));
    }
    return result;
  } catch (error) {
    throw new Error(
      `AGENT_A2A_ALLOWED_EDGES is invalid: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

function isInvocationScope(scope: ToolScope): boolean {
  return Boolean(scope.agentId && scope.userId && scope.spaceId && scope.taskId && scope.runId);
}

function isTerminal(status: RunStatus): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function delayWithSignal(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    let timer: NodeJS.Timeout;
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason ?? new Error("Agent run cancelled"));
    };
    const done = () => {
      signal.removeEventListener("abort", abort);
      resolve();
    };
    timer = setTimeout(done, milliseconds);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
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

async function getInvocation(database: Pool, invocationId: string) {
  const result = await database.query(
    `SELECT id, task_id, agent, caller, parent_id, tool_call_id, depth, inbound_text, status,
            result_text, error, created_at, started_at, finished_at
     FROM web_invocations WHERE id = $1`,
    [invocationId],
  );
  return result.rows[0];
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

function asIso(value: string | Date): string {
  return new Date(value).toISOString();
}

function decodeResult(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
