/**
 * M8 production MemoryPort over the PostgreSQL agent memory tools (memory.search/remember/forget,
 * src/memory-store.ts), with an injected durable audit writer required for every mutation.
 * Returned items are always `trust: "untrusted"`: memory is data, never instructions.
 */
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentPorts, JsonValue, MemoryItem } from "../contracts/index.js";
import type { MemoryAuditWriter } from "../session/memory-provider.js";
import {
  type CallOptions,
  failure,
  granted,
  hostScope,
  ID,
  inactive,
  jsonBytes,
  poolScope,
} from "./host-outcome.js";

type Row = { id: string; key: string | null; text: string; tags: string[] };
const LIMITATION =
  "Agent memory is private per user and agent; the store has no revisions (revision is '1'). Expiry is enforced by PostgreSQL.";

export function createHostMemoryPort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
  audit?: MemoryAuditWriter,
): AgentPorts["memory"] {
  const declared = manifest.requiredPorts.includes("memory");
  const scope = hostScope(manifest, context);
  const call = (tool: string, input: unknown, options: CallOptions, key?: string) =>
    context.pool.call(tool, input, poolScope(manifest, context, options.signal, key), manifest.id);
  const gate = (tool: string, options: CallOptions) => {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    if (!granted(manifest, context, tool))
      return failure("denied", "memory_not_granted", correlationId);
    if (inactive(options)) return failure("failed", "inactive_call", correlationId);
    if ((tool === "memory.remember" || tool === "memory.forget") && !audit)
      return failure("failed", "memory_audit_unavailable", correlationId);
    return undefined;
  };
  const item = (row: Row): MemoryItem => {
    let content: JsonValue = row.text;
    try {
      content = JSON.parse(row.text) as JsonValue;
    } catch {
      // Plain-text notes stay strings.
    }
    const tag = (name: string) =>
      row.tags.find((entry) => entry.startsWith(`${name}:`))?.slice(name.length + 1);
    const sensitivity = tag("sensitivity");
    return {
      id: row.key ?? row.id,
      revision: "1",
      content,
      trust: "untrusted",
      scope: "agent",
      audience: tag("audience") ?? scope.audience,
      sensitivity: sensitivity === "public" || sensitivity === "private" ? sensitivity : "internal",
      expiresAt: tag("expiresAt") ?? null,
      provenance: [],
    };
  };
  const search = async (query: string, options: CallOptions) =>
    (await call("memory.search", { query }, options)) as Row[];
  const record = async (operation: "commit" | "delete", resource: string, success: boolean) => {
    if (!audit) throw new Error("memory_audit_unavailable");
    await audit.recordAudit({
      workspaceId: scope.workspaceId,
      operation,
      actor: `${scope.actorId}/${manifest.id}`,
      resource,
      details: { runId: scope.runId },
      success,
    });
  };

  return {
    async read(_input, options) {
      const denied = gate("memory.search", options);
      if (denied) return denied;
      // The PostgreSQL store has no read-by-id; search is the only supported lookup.
      return failure("failed", "memory_read_unsupported", correlationId);
    },
    async search(input, options) {
      const denied = gate("memory.search", options);
      if (denied) return denied;
      if (input.scope !== "agent")
        return failure("denied", "memory_scope_unsupported", correlationId);
      let rows: Row[];
      try {
        rows = await search(input.query, options);
      } catch {
        return failure("failed", "memory_failed", correlationId);
      }
      const output: MemoryItem[] = [];
      for (const row of rows.slice(0, input.limit)) {
        const next = item(row);
        if (jsonBytes([...output, next]) > input.maxBytes) break;
        output.push(next);
      }
      return { status: "ok", output, evidence: [], limitations: [LIMITATION] };
    },
    async remember(input, options) {
      const denied = gate("memory.remember", options);
      if (denied) return denied;
      if (input.scope !== "agent")
        return failure("denied", "memory_scope_unsupported", correlationId);
      if (input.expectedRevision !== null)
        return failure("failed", "memory_revision_unsupported", correlationId);
      if (!ID.test(input.id)) return failure("denied", "invalid_memory_id", correlationId);
      const expiresAt = memoryExpiration(input.expiresAt);
      if (!expiresAt) return failure("denied", "invalid_memory_expiration", correlationId);
      const text =
        typeof input.content === "string" ? input.content : JSON.stringify(input.content);
      try {
        await call(
          "memory.remember",
          {
            key: input.id,
            text,
            tags: [
              `sensitivity:${input.sensitivity}`,
              `audience:${input.audience}`,
              `expiresAt:${expiresAt}`,
            ],
          },
          options,
          input.idempotencyKey,
        );
      } catch {
        await record("commit", input.id, false).catch(() => undefined);
        return failure("unknown", "memory_outcome_unknown", correlationId);
      }
      try {
        await record("commit", input.id, true);
      } catch {
        return failure("unknown", "memory_audit_failed", correlationId);
      }
      return {
        status: "ok",
        output: item({
          id: input.id,
          key: input.id,
          text,
          tags: [
            `sensitivity:${input.sensitivity}`,
            `audience:${input.audience}`,
            `expiresAt:${expiresAt}`,
          ],
        }),
        evidence: [],
        limitations: [LIMITATION],
      };
    },
    async forget(input, options) {
      const denied = gate("memory.forget", options);
      if (denied) return denied;
      let deleted = false;
      try {
        const result = (await call(
          "memory.forget",
          { id: input.id },
          options,
          input.idempotencyKey,
        )) as { deleted?: boolean };
        deleted = result.deleted === true;
      } catch {
        await record("delete", input.id, false).catch(() => undefined);
        return failure("unknown", "memory_outcome_unknown", correlationId);
      }
      try {
        await record("delete", input.id, deleted);
      } catch {
        return failure("unknown", "memory_audit_failed", correlationId);
      }
      if (!deleted) return failure("failed", "memory_not_found", correlationId);
      return {
        status: "ok",
        output: { revision: input.expectedRevision, deleted: true },
        evidence: [],
        limitations: [LIMITATION],
      };
    },
  };
}

/** Agent memory receives a finite host-owned lifetime even if the agent omits one. */
function memoryExpiration(requested: string | null): string | undefined {
  const configured = Number(process.env.MEMORY_RETENTION_DAYS ?? 365);
  const configuredDays = Math.floor(configured);
  const retentionDays =
    Number.isFinite(configuredDays) && configuredDays >= 1 ? Math.min(configuredDays, 3650) : 365;
  const now = Date.now();
  const maxExpiry = now + retentionDays * 86_400_000;
  if (requested === null) return new Date(maxExpiry).toISOString();
  const timestamp = Date.parse(requested);
  if (!Number.isFinite(timestamp) || timestamp <= now) return undefined;
  return new Date(Math.min(timestamp, maxExpiry)).toISOString();
}
