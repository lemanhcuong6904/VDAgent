/**
 * A2A gateway - M12.5 (optional, off unless A2A_ENABLED=true)
 *
 * A2A 1.0 JSON-RPC binding over the existing durable path: an external SendMessage
 * becomes the same web task + invocation + run the worker already executes. The
 * caller's user and space come from server-side client config, never from the
 * request, so the gateway cannot reach anything the mapped user could not.
 *
 * Wire format follows the normative a2a.proto (ProtoJSON: lowerCamelCase fields,
 * enums as their SCREAMING_SNAKE names) and the method/error tables of the 1.0 spec.
 */

import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import type { Context, Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { Pool } from "pg";
import { RateLimiter } from "./rate-limit.js";
import type { AgentPool } from "./registry.js";
import type { RunLedger } from "./run-ledger.js";
import { createAgentMessageTaskOnClient } from "./web-api.js";

export const A2A_PROTOCOL_VERSION = "1.0";
export const A2A_PATH = "/a2a";
export const AGENT_CARD_PATH = "/.well-known/agent-card.json";
export const MAX_A2A_TEXT = 4_000;

/** A2A-specific JSON-RPC codes from the 1.0 error table, plus the JSON-RPC standard ones. */
export const A2A_ERRORS = {
  parse: -32700,
  invalidRequest: -32600,
  methodNotFound: -32601,
  invalidParams: -32602,
  internal: -32603,
  taskNotFound: -32001,
  taskNotCancelable: -32002,
  pushNotSupported: -32003,
  unsupportedOperation: -32004,
  contentTypeNotSupported: -32005,
  extendedCardNotConfigured: -32007,
  versionNotSupported: -32009,
} as const;

export type A2aTaskState =
  | "TASK_STATE_SUBMITTED"
  | "TASK_STATE_WORKING"
  | "TASK_STATE_COMPLETED"
  | "TASK_STATE_FAILED"
  | "TASK_STATE_CANCELED"
  | "TASK_STATE_REJECTED";

const TERMINAL: ReadonlySet<A2aTaskState> = new Set([
  "TASK_STATE_COMPLETED",
  "TASK_STATE_FAILED",
  "TASK_STATE_CANCELED",
  "TASK_STATE_REJECTED",
]);

export interface A2aClient {
  id: string;
  /** sha256 hex of the bearer token; the plaintext token is never configured. */
  tokenSha256: string;
  userId: string;
  spaceId: string;
  /** Agent ids this client may address, exposed as A2A skills. */
  skills: string[];
  /** Requests per minute. */
  rateLimit: number;
}

export interface A2aGatewayDependencies {
  database: Pool;
  pluginRegistry: AgentPool;
  runLedger: RunLedger;
  clients: readonly A2aClient[];
  /** Public base URL placed in the Agent Card interface. */
  publicUrl: string;
  streamPollMs?: number;
  streamMaxMs?: number;
}

const IDENTIFIER = /^[a-zA-Z0-9._:-]{1,128}$/;

/** Parse `A2A_CLIENTS` JSON. Throws on anything malformed: a bad config must not start. */
export function parseA2aClients(raw: string | undefined): A2aClient[] {
  if (!raw?.trim()) return [];
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) throw new Error("A2A_CLIENTS must be a JSON array");
  const seen = new Set<string>();
  return parsed.map((entry, index) => {
    if (!isRecord(entry)) throw new Error(`A2A_CLIENTS[${index}] must be an object`);
    const { id, tokenSha256, userId, spaceId, skills, rateLimit } = entry;
    for (const [name, value] of [
      ["id", id],
      ["userId", userId],
      ["spaceId", spaceId],
    ] as const) {
      if (typeof value !== "string" || !IDENTIFIER.test(value)) {
        throw new Error(`A2A_CLIENTS[${index}].${name} is invalid`);
      }
    }
    if (typeof tokenSha256 !== "string" || !/^[0-9a-f]{64}$/.test(tokenSha256)) {
      throw new Error(`A2A_CLIENTS[${index}].tokenSha256 must be a lowercase sha256 hex digest`);
    }
    if (
      !Array.isArray(skills) ||
      skills.length === 0 ||
      !skills.every((skill) => typeof skill === "string" && IDENTIFIER.test(skill))
    ) {
      throw new Error(`A2A_CLIENTS[${index}].skills must list at least one agent id`);
    }
    if (seen.has(id as string)) throw new Error(`A2A_CLIENTS has duplicate id '${id}'`);
    seen.add(id as string);
    const limit = rateLimit === undefined ? 60 : rateLimit;
    if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 10_000) {
      throw new Error(`A2A_CLIENTS[${index}].rateLimit must be an integer from 1 to 10000`);
    }
    return {
      id: id as string,
      tokenSha256,
      userId: userId as string,
      spaceId: spaceId as string,
      skills: [...(skills as string[])],
      rateLimit: limit,
    };
  });
}

/** Compare against every client so response time does not reveal which one matched. */
export function authenticateA2a(
  authorization: string | undefined,
  clients: readonly A2aClient[],
): A2aClient | undefined {
  const token = /^Bearer\s+(.+)$/i.exec(authorization ?? "")?.[1]?.trim();
  if (!token) return undefined;
  const presented = createHash("sha256").update(token).digest();
  let match: A2aClient | undefined;
  for (const client of clients) {
    if (timingSafeEqual(presented, Buffer.from(client.tokenSha256, "hex")) && !match)
      match = client;
  }
  return match;
}

export function buildAgentCard(
  dependencies: Pick<A2aGatewayDependencies, "pluginRegistry" | "clients" | "publicUrl">,
) {
  // Only agents some client is configured to reach are advertised; the rest of the
  // internal registry stays invisible to the outside.
  const exposed = [...new Set(dependencies.clients.flatMap((client) => client.skills))].sort();
  const agents = dependencies.pluginRegistry.list();
  return {
    name: "team-6-cai",
    description: "Analytics agents reachable through the platform's durable run ledger.",
    supportedInterfaces: [
      {
        url: `${dependencies.publicUrl.replace(/\/$/, "")}${A2A_PATH}`,
        protocolBinding: "JSONRPC",
        protocolVersion: A2A_PROTOCOL_VERSION,
      },
    ],
    version: "0.1.0",
    capabilities: { streaming: true, pushNotifications: false, extendedAgentCard: false },
    securitySchemes: {
      bearer: {
        httpAuthSecurityScheme: {
          scheme: "Bearer",
          description: "Per-client token issued by the operator",
        },
      },
    },
    securityRequirements: [{ schemes: { bearer: { list: [] } } }],
    defaultInputModes: ["text/plain", "application/json"],
    defaultOutputModes: ["text/plain"],
    skills: exposed
      .map((id) => agents.find((agent) => agent.id === id))
      .filter((agent): agent is NonNullable<typeof agent> => agent !== undefined)
      .map((agent) => ({
        id: agent.id,
        name: agent.name ?? agent.id,
        description: agent.description ?? agent.id,
        tags: [...(agent.capabilities ?? [])],
      })),
  };
}

// ---- Task projection -------------------------------------------------------

type TaskRow = {
  id: string;
  context_id: string;
  run_status: string;
  invocation_status: string | null;
  result_text: string | null;
  invocation_error: string | null;
  inbound_text: string | null;
  message_id: string;
  created_at: Date;
  updated_at: Date;
  latest_seq: string | null;
};

/** The invocation reaches terminal after the run writes its reply, so it decides first. */
export function mapTaskState(runStatus: string, invocationStatus: string | null): A2aTaskState {
  switch (invocationStatus) {
    case "completed":
      return "TASK_STATE_COMPLETED";
    case "failed":
      return "TASK_STATE_FAILED";
    case "cancelled":
      return "TASK_STATE_CANCELED";
    case "rejected":
      return "TASK_STATE_REJECTED";
  }
  if (runStatus === "cancelled") return "TASK_STATE_CANCELED";
  if (runStatus === "queued" || runStatus === "leased") return "TASK_STATE_SUBMITTED";
  return "TASK_STATE_WORKING";
}

export function toA2aTask(row: TaskRow) {
  const state = mapTaskState(row.run_status, row.invocation_status);
  const reply =
    state === "TASK_STATE_COMPLETED"
      ? row.result_text
      : state === "TASK_STATE_FAILED" || state === "TASK_STATE_REJECTED"
        ? (row.invocation_error ?? "The task failed")
        : null;
  return {
    id: row.id,
    contextId: row.context_id,
    status: {
      state,
      timestamp: new Date(row.updated_at).toISOString(),
      ...(reply !== null && {
        message: {
          messageId: `${row.id}:status`,
          contextId: row.context_id,
          taskId: row.id,
          role: "ROLE_AGENT",
          parts: [{ text: reply }],
        },
      }),
    },
    artifacts:
      state === "TASK_STATE_COMPLETED" && row.result_text
        ? [{ artifactId: `${row.id}:reply`, name: "reply", parts: [{ text: row.result_text }] }]
        : [],
    history: row.inbound_text
      ? [
          {
            messageId: row.message_id,
            contextId: row.context_id,
            taskId: row.id,
            role: "ROLE_USER",
            parts: [{ text: row.inbound_text }],
          },
        ]
      : [],
  };
}

async function loadTask(
  database: Pool,
  clientId: string,
  taskId: string,
): Promise<TaskRow | undefined> {
  const result = await database.query<TaskRow>(
    `SELECT a.id, a.context_id, a.message_id, a.created_at,
            r.status AS run_status, r.updated_at,
            i.status AS invocation_status, i.result_text, i.error AS invocation_error, i.inbound_text,
            (SELECT max(seq) FROM platform_run_events e WHERE e.run_id = a.run_id) AS latest_seq
     FROM a2a_tasks a
     JOIN platform_runs r ON r.id = a.run_id
     LEFT JOIN web_invocations i ON i.task_id = a.web_task_id AND i.caller = 'user'
     WHERE a.id = $1 AND a.client_id = $2`,
    [taskId, clientId],
  );
  return result.rows[0];
}

// ---- JSON-RPC --------------------------------------------------------------

class A2aError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

type Rpc = { id: string | number | null; method: string; params: Record<string, unknown> };

function rpcResult(id: Rpc["id"], result: unknown) {
  return { jsonrpc: "2.0", id, result };
}

function rpcError(id: Rpc["id"], code: number, message: string) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

/** Validate a user message and flatten its parts to the agent's text input. */
export function acceptMessage(message: unknown): {
  messageId: string;
  contextId?: string;
  text: string;
  skillId?: string;
} {
  if (!isRecord(message))
    throw new A2aError(A2A_ERRORS.invalidParams, "params.message is required");
  if (typeof message.messageId !== "string" || !IDENTIFIER.test(message.messageId)) {
    throw new A2aError(A2A_ERRORS.invalidParams, "message.messageId is required");
  }
  if (message.role !== "ROLE_USER")
    throw new A2aError(A2A_ERRORS.invalidParams, "message.role must be ROLE_USER");
  if (message.taskId !== undefined) {
    // Each message starts a new task here; there is no input-required continuation yet.
    throw new A2aError(
      A2A_ERRORS.unsupportedOperation,
      "Continuing an existing task is not supported",
    );
  }
  if (
    message.contextId !== undefined &&
    (typeof message.contextId !== "string" || !IDENTIFIER.test(message.contextId))
  ) {
    throw new A2aError(A2A_ERRORS.invalidParams, "message.contextId is invalid");
  }
  if (!Array.isArray(message.parts) || message.parts.length === 0) {
    throw new A2aError(A2A_ERRORS.invalidParams, "message.parts must not be empty");
  }
  const texts = message.parts.map((part) => {
    if (!isRecord(part)) throw new A2aError(A2A_ERRORS.invalidParams, "Invalid part");
    if (typeof part.text === "string") return part.text;
    if (part.data !== undefined) return JSON.stringify(part.data);
    // url/raw are file content; this gateway has no file intake path.
    throw new A2aError(A2A_ERRORS.contentTypeNotSupported, "Only text and data parts are accepted");
  });
  const text = texts.join("\n").trim();
  if (!text) throw new A2aError(A2A_ERRORS.invalidParams, "message has no content");
  if (text.length > MAX_A2A_TEXT) {
    throw new A2aError(
      A2A_ERRORS.invalidParams,
      `message content must be at most ${MAX_A2A_TEXT} characters`,
    );
  }
  const metadata = isRecord(message.metadata) ? message.metadata : {};
  return {
    messageId: message.messageId,
    contextId: message.contextId as string | undefined,
    text,
    skillId: typeof metadata.skillId === "string" ? metadata.skillId : undefined,
  };
}

async function sendMessage(
  dependencies: A2aGatewayDependencies,
  client: A2aClient,
  params: Record<string, unknown>,
) {
  const accepted = acceptMessage(params.message);
  const skillId = accepted.skillId ?? (client.skills.length === 1 ? client.skills[0] : undefined);
  if (!skillId)
    throw new A2aError(
      A2A_ERRORS.invalidParams,
      "message.metadata.skillId is required for this client",
    );
  if (!client.skills.includes(skillId) || !dependencies.pluginRegistry.get(skillId)) {
    // Same answer for "not granted" and "does not exist".
    throw new A2aError(A2A_ERRORS.invalidParams, "Unknown skill");
  }
  const contentHash = createHash("sha256").update(`${skillId}\n${accepted.text}`).digest("hex");
  const database = dependencies.database;
  const connection = await database.connect();
  try {
    await connection.query("BEGIN");
    // Serialize retries of one messageId so a concurrent duplicate waits and then reads.
    await connection.query("SELECT pg_advisory_xact_lock(hashtext($1))", [
      `a2a:${client.id}:${accepted.messageId}`,
    ]);
    const existing = await connection.query<{ id: string; content_hash: string }>(
      "SELECT id, content_hash FROM a2a_tasks WHERE client_id = $1 AND message_id = $2",
      [client.id, accepted.messageId],
    );
    if (existing.rows[0]) {
      await connection.query("COMMIT");
      if (existing.rows[0].content_hash !== contentHash) {
        throw new A2aError(
          A2A_ERRORS.invalidParams,
          "messageId was already used with different content",
        );
      }
      return existing.rows[0].id;
    }
    const created = await createAgentMessageTaskOnClient(connection, {
      userId: client.userId,
      spaceId: client.spaceId,
      agent: skillId,
      content: accepted.text,
      runLedger: dependencies.runLedger,
      idempotencyKey: `a2a:${client.id}:${accepted.messageId}`,
    });
    const taskId = `a2a_${randomUUID().replaceAll("-", "").slice(0, 16)}`;
    await connection.query(
      `INSERT INTO a2a_tasks (id, client_id, context_id, message_id, skill_id, content_hash, space_id, user_id, web_task_id, run_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [
        taskId,
        client.id,
        accepted.contextId ?? `ctx_${randomUUID().replaceAll("-", "").slice(0, 16)}`,
        accepted.messageId,
        skillId,
        contentHash,
        client.spaceId,
        client.userId,
        created.taskId,
        created.runId,
      ],
    );
    await connection.query("COMMIT");
    return taskId;
  } catch (failure) {
    await connection.query("ROLLBACK").catch(() => undefined);
    throw failure;
  } finally {
    connection.release();
  }
}

async function requireTask(database: Pool, client: A2aClient, params: Record<string, unknown>) {
  const id = params.id;
  if (typeof id !== "string" || !IDENTIFIER.test(id))
    throw new A2aError(A2A_ERRORS.invalidParams, "params.id is required");
  const row = await loadTask(database, client.id, id);
  // Another client's task and a missing task are the same error.
  if (!row) throw new A2aError(A2A_ERRORS.taskNotFound, "Task not found");
  return row;
}

async function cancelTask(
  dependencies: A2aGatewayDependencies,
  client: A2aClient,
  params: Record<string, unknown>,
) {
  const row = await requireTask(dependencies.database, client, params);
  if (TERMINAL.has(mapTaskState(row.run_status, row.invocation_status))) {
    throw new A2aError(A2A_ERRORS.taskNotCancelable, "Task is already in a terminal state");
  }
  const run = await dependencies.database.query<{ run_id: string }>(
    "SELECT run_id FROM a2a_tasks WHERE id = $1 AND client_id = $2",
    [row.id, client.id],
  );
  const cancelled = await dependencies.runLedger.cancel(
    run.rows[0].run_id,
    client.spaceId,
    client.userId,
  );
  if (!cancelled) throw new A2aError(A2A_ERRORS.taskNotCancelable, "Task is not cancelable");
  const updated = await loadTask(dependencies.database, client.id, row.id);
  return toA2aTask(updated ?? row);
}

/**
 * SSE of StreamResponse frames. The first frame is always the full Task, so a client
 * resubscribing after a drop reconciles from a snapshot rather than a partial diff.
 */
function streamTask(
  context: Context,
  dependencies: A2aGatewayDependencies,
  client: A2aClient,
  rpcId: Rpc["id"],
  taskId: string,
) {
  const pollMs = dependencies.streamPollMs ?? 1_000;
  const deadline = Date.now() + (dependencies.streamMaxMs ?? 600_000);
  return streamSSE(context, async (stream) => {
    const signal = context.req.raw.signal;
    let row = await loadTask(dependencies.database, client.id, taskId);
    if (!row) return;
    let task = toA2aTask(row);
    await stream.writeSSE({
      id: row.latest_seq ?? "0",
      data: JSON.stringify(rpcResult(rpcId, { task })),
    });
    let lastState = task.status.state;
    while (!TERMINAL.has(lastState) && !signal.aborted && Date.now() < deadline) {
      await stream.sleep(pollMs);
      row = await loadTask(dependencies.database, client.id, taskId);
      if (!row) return;
      task = toA2aTask(row);
      if (task.status.state === lastState) continue;
      for (const artifact of task.artifacts) {
        await stream.writeSSE({
          id: row.latest_seq ?? "0",
          data: JSON.stringify(
            rpcResult(rpcId, {
              artifactUpdate: {
                taskId,
                contextId: task.contextId,
                artifact,
                append: false,
                lastChunk: true,
              },
            }),
          ),
        });
      }
      await stream.writeSSE({
        id: row.latest_seq ?? "0",
        data: JSON.stringify(
          rpcResult(rpcId, {
            statusUpdate: { taskId, contextId: task.contextId, status: task.status },
          }),
        ),
      });
      lastState = task.status.state;
    }
  });
}

// ---- Registration ----------------------------------------------------------

export function registerA2aGateway(app: Hono, dependencies: A2aGatewayDependencies): void {
  const limiters = new Map(
    dependencies.clients.map((client) => [
      client.id,
      new RateLimiter({ windowMs: 60_000, maxRequests: client.rateLimit }),
    ]),
  );

  app.get(AGENT_CARD_PATH, (context) => context.json(buildAgentCard(dependencies)));

  app.post(A2A_PATH, async (context) => {
    const client = authenticateA2a(context.req.header("authorization"), dependencies.clients);
    if (!client) {
      context.header("WWW-Authenticate", 'Bearer realm="a2a"');
      return context.json(
        rpcError(null, A2A_ERRORS.invalidRequest, "Authentication required"),
        401,
      );
    }
    if (!limiters.get(client.id)?.allow(client.id)) {
      context.header("Retry-After", "60");
      return context.json(rpcError(null, A2A_ERRORS.invalidRequest, "Rate limit exceeded"), 429);
    }

    let body: unknown;
    try {
      body = JSON.parse(await context.req.text());
    } catch {
      return context.json(rpcError(null, A2A_ERRORS.parse, "Parse error"));
    }
    if (!isRecord(body) || body.jsonrpc !== "2.0" || typeof body.method !== "string") {
      return context.json(rpcError(null, A2A_ERRORS.invalidRequest, "Invalid JSON-RPC request"));
    }
    const rpc: Rpc = {
      id: typeof body.id === "string" || typeof body.id === "number" ? body.id : null,
      method: body.method,
      params: isRecord(body.params) ? body.params : {},
    };

    // The spec says an absent version means 0.3, which this gateway does not speak.
    const version = context.req.header("a2a-version")?.trim() || "0.3";
    if (version !== A2A_PROTOCOL_VERSION) {
      return context.json(
        rpcError(rpc.id, A2A_ERRORS.versionNotSupported, `A2A version ${version} is not supported`),
      );
    }

    try {
      switch (rpc.method) {
        case "SendMessage": {
          const taskId = await sendMessage(dependencies, client, rpc.params);
          const row = await loadTask(dependencies.database, client.id, taskId);
          return context.json(rpcResult(rpc.id, { task: row ? toA2aTask(row) : undefined }));
        }
        case "SendStreamingMessage": {
          const taskId = await sendMessage(dependencies, client, rpc.params);
          return streamTask(context, dependencies, client, rpc.id, taskId);
        }
        case "SubscribeToTask": {
          const row = await requireTask(dependencies.database, client, rpc.params);
          return streamTask(context, dependencies, client, rpc.id, row.id);
        }
        case "GetTask": {
          const row = await requireTask(dependencies.database, client, rpc.params);
          return context.json(rpcResult(rpc.id, toA2aTask(row)));
        }
        case "CancelTask":
          return context.json(
            rpcResult(rpc.id, await cancelTask(dependencies, client, rpc.params)),
          );
        case "ListTasks":
          throw new A2aError(A2A_ERRORS.unsupportedOperation, "ListTasks is not supported");
        case "CreateTaskPushNotificationConfig":
        case "GetTaskPushNotificationConfig":
        case "ListTaskPushNotificationConfigs":
        case "DeleteTaskPushNotificationConfig":
          throw new A2aError(A2A_ERRORS.pushNotSupported, "Push notifications are not supported");
        case "GetExtendedAgentCard":
          throw new A2aError(A2A_ERRORS.extendedCardNotConfigured, "No extended agent card");
        default:
          throw new A2aError(A2A_ERRORS.methodNotFound, "Method not found");
      }
    } catch (failure) {
      if (failure instanceof A2aError)
        return context.json(rpcError(rpc.id, failure.code, failure.message));
      // Internal detail stays in the server log path, never in the response.
      return context.json(rpcError(rpc.id, A2A_ERRORS.internal, "Internal error"));
    }
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
