import { createHash } from "node:crypto";
import { Ajv2020 } from "ajv/dist/2020.js";
import { EvidenceRefSchema } from "../contracts/generated/evidence-ref.js";
import type { CallOptions, MemoryItem, MemoryPort, PortOutcome } from "../contracts/ports.js";
import { runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

type Mutation = "remember" | "forget";
type Operation = Mutation | "read" | "search";
type StoredVersion = { at: number; revision: string; item: MemoryItem | null };
type MutationReceipt = { id: string; revision: string; deleted: boolean };
const validId = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const timestamp = (value: unknown): number => {
  if (typeof value !== "string") return NaN;
  const time = Date.parse(value);
  return Number.isFinite(time) && new Date(time).toISOString() === value ? time : NaN;
};

/** Isolated host scope, bounded revision history and a synthetic effect ledger; no persistence. */
export function createFakeMemoryPort(config: {
  workspaceId: string;
  audience: string;
  scopes: readonly MemoryItem["scope"][];
  sensitivities: readonly MemoryItem["sensitivity"][];
  clock: TestClock;
  maxBytes: number;
  maxItems: number;
  maxMutations: number;
  /** Fault hook runs before the effect; use a deferred promise with ManualClock. */
  before?: (operation: Operation, signal: AbortSignal) => Promise<void>;
}): MemoryPort {
  const { clock, maxBytes, maxItems, maxMutations, workspaceId, audience, before } = config;
  for (const value of [maxBytes, maxItems, maxMutations])
    if (!Number.isSafeInteger(value) || value < 1) throw new Error("Invalid memory limits");
  if (!validId(workspaceId) || !validId(audience)) throw new Error("Invalid memory scope");
  const scopes = new Set(config.scopes);
  const sensitivities = new Set(config.sensitivities);
  if (
    [...scopes].some((scope) => !["user", "agent", "workspace"].includes(scope)) ||
    [...sensitivities].some((value) => !["public", "internal", "private"].includes(value))
  )
    throw new Error("Invalid memory grants");
  const validateEvidence = new Ajv2020({ strict: true }).compile(EvidenceRefSchema);
  const records = new Map<
    string,
    { revision: string; scope: MemoryItem["scope"]; versions: StoredVersion[] }
  >();
  // Receipts contain identities only: forget/expiry must not leave content in replay caches.
  const ledger = new Map<
    string,
    { fingerprint: string; result: Promise<PortOutcome<MutationReceipt>> }
  >();
  let revision = 0;
  const denied = <T>(code: string): PortOutcome<T> => ({
    status: "denied",
    error: {
      code,
      class: "policy",
      retryable: false,
      safeMessage: code,
      correlationId: "fake-memory",
    },
    evidence: [],
  });
  const ok = <T>(output: T): PortOutcome<T> => ({
    status: "ok",
    output,
    evidence: [],
    limitations: ["Synthetic scoped memory; not durable evidence"],
  });
  function parse<T>(input: T, fields: string[]): T | null {
    try {
      const value = JSON.parse(encodeBoundedJson(input, maxBytes));
      if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== fields.length ||
        fields.some((field) => !Object.hasOwn(value, field))
      )
        return null;
      return value as T;
    } catch {
      return null;
    }
  }
  function purge(): void {
    for (const record of records.values())
      for (const version of record.versions)
        if (
          version.item?.expiresAt !== null &&
          version.item &&
          timestamp(version.item.expiresAt) <= clock.now()
        )
          version.item = null;
  }
  async function call<T>(
    operation: Operation,
    options: CallOptions,
    effect: () => PortOutcome<T>,
    cap = maxBytes,
  ): Promise<PortOutcome<T>> {
    const result = await runFakeCall(
      async (signal) => {
        if (before) await before(operation, signal);
        if (signal.aborted) throw new Error("inactive_call");
        purge();
        return effect();
      },
      options,
      {
        maxOutputBytes: cap,
        correlationId: "fake-memory",
        effect: operation === "remember" || operation === "forget" ? "write" : "read",
      },
      clock,
    );
    return result.status === "ok" ? result.output : result;
  }
  async function mutate(
    operation: Mutation,
    input: { id: string; idempotencyKey: string },
    options: CallOptions,
    effect: () => PortOutcome<MutationReceipt>,
  ): Promise<PortOutcome<MutationReceipt>> {
    if (!validId(input.idempotencyKey)) return denied("invalid_idempotency_key");
    if (
      options.signal.aborted ||
      !Number.isFinite(options.deadline) ||
      options.deadline <= clock.now()
    )
      return denied("inactive_call");
    const fingerprint = createHash("sha256").update(canonical({ operation, input })).digest("hex");
    const previous = ledger.get(input.idempotencyKey);
    if (previous) {
      if (previous.fingerprint !== fingerprint) return denied("idempotency_conflict");
      // A replay has its own cancellation/deadline, without aborting the original effect.
      const replay = await runFakeCall(
        () => previous.result,
        options,
        {
          maxOutputBytes: maxBytes,
          correlationId: "fake-memory",
          effect: "write",
        },
        clock,
      );
      return replay.status === "ok" ? replay.output : replay;
    }
    if (ledger.size >= maxMutations) return denied("mutation_limit");
    let resolve!: (value: PortOutcome<MutationReceipt>) => void;
    const result = new Promise<PortOutcome<MutationReceipt>>((done) => {
      resolve = done;
    });
    ledger.set(input.idempotencyKey, { fingerprint, result });
    void call(operation, options, effect).then(resolve);
    return structuredClone(await result);
  }
  return {
    read(input, options) {
      const value = parse(input, ["id"]);
      if (!value || !validId(value.id)) return Promise.resolve(denied("invalid_read"));
      return call("read", options, () => {
        const record = records.get(value.id);
        return ok(
          record?.versions.find(({ revision }) => revision === record.revision)?.item ?? null,
        );
      });
    },
    search(input, options) {
      const value = parse(input, ["query", "scope", "limit", "maxBytes", "asOf"]);
      if (
        !value ||
        typeof value.query !== "string" ||
        !scopes.has(value.scope) ||
        !Number.isSafeInteger(value.limit) ||
        value.limit < 1 ||
        value.limit > maxItems ||
        !Number.isSafeInteger(value.maxBytes) ||
        value.maxBytes < 1 ||
        value.maxBytes > maxBytes ||
        !Number.isFinite(timestamp(value.asOf)) ||
        timestamp(value.asOf) > clock.now()
      )
        return Promise.resolve(denied("invalid_search"));
      return call(
        "search",
        options,
        () => {
          const found: MemoryItem[] = [];
          for (const [id, record] of [...records].sort(([a], [b]) =>
            a < b ? -1 : a > b ? 1 : 0,
          )) {
            const version = record.versions.findLast((entry) => entry.at <= timestamp(value.asOf));
            if (
              version?.item?.scope === value.scope &&
              JSON.stringify(version.item.content).toLowerCase().includes(value.query.toLowerCase())
            ) {
              found.push({ ...version.item, id });
              if (found.length === value.limit) break;
            }
          }
          return ok(found);
        },
        value.maxBytes,
      );
    },
    async remember(input, options) {
      const value = parse(input, [
        "id",
        "expectedRevision",
        "content",
        "scope",
        "audience",
        "sensitivity",
        "expiresAt",
        "provenance",
        "idempotencyKey",
      ]);
      if (
        !value ||
        !validId(value.id) ||
        !(value.expectedRevision === null || validId(value.expectedRevision)) ||
        !scopes.has(value.scope) ||
        value.audience !== audience ||
        !sensitivities.has(value.sensitivity) ||
        !(value.expiresAt === null || Number.isFinite(timestamp(value.expiresAt))) ||
        !Array.isArray(value.provenance) ||
        value.provenance.some((ref) => !validateEvidence(ref) || ref.workspaceId !== workspaceId)
      )
        return denied("invalid_memory_input");
      const receipt = await mutate("remember", value, options, () => {
        const current = records.get(value.id);
        if ((current?.revision ?? null) !== value.expectedRevision)
          return denied("revision_conflict");
        if (!current && records.size >= maxItems) return denied("item_limit");
        if (current && current.scope !== value.scope) return denied("scope_change");
        if (value.expiresAt !== null && timestamp(value.expiresAt) <= clock.now())
          return denied("expired_memory");
        const next = String(revision + 1);
        const item: MemoryItem = {
          id: value.id,
          revision: next,
          content: value.content,
          trust: "untrusted",
          scope: value.scope,
          audience,
          sensitivity: value.sensitivity,
          expiresAt: value.expiresAt,
          provenance: value.provenance,
        };
        // Bound the response before committing state; no known local oversized write is applied.
        try {
          encodeBoundedJson(ok(item), maxBytes);
        } catch {
          return denied("output_limit");
        }
        revision++;
        records.set(value.id, {
          revision: next,
          scope: value.scope,
          versions: [...(current?.versions ?? []), { at: clock.now(), revision: next, item }],
        });
        return ok({ id: value.id, revision: next, deleted: false });
      });
      if (receipt.status !== "ok") return receipt;
      purge();
      const item = records
        .get(receipt.output.id)
        ?.versions.find((entry) => entry.revision === receipt.output.revision)?.item;
      return item ? structuredClone(ok(item)) : denied("replay_content_unavailable");
    },
    async forget(input, options) {
      const value = parse(input, ["id", "expectedRevision", "idempotencyKey"]);
      if (!value || !validId(value.id) || !validId(value.expectedRevision))
        return denied("invalid_forget");
      const receipt = await mutate("forget", value, options, () => {
        const current = records.get(value.id);
        if (!current || current.revision !== value.expectedRevision)
          return denied("revision_conflict");
        const next = String(++revision);
        records.set(value.id, { revision: next, scope: current.scope, versions: [] });
        return ok({ id: value.id, revision: next, deleted: true });
      });
      return receipt.status === "ok"
        ? ok({ revision: receipt.output.revision, deleted: true })
        : receipt;
    },
  };
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
