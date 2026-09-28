// M2.2/M3.2: the production host factory binds canonical ports to the shared runtime and pool.
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentContext } from "../../src/agent-contract.js";
import type { AgentManifest, AgentModule, JsonValue } from "../../src/contracts/index.js";
import { createHostPorts, hostScope, UNTRUSTED_GUARD } from "../../src/ports/host-factory.js";
import { moduleAsPlugin } from "../../src/ports/module-plugin.js";
import { activeModulePlugins, createExternalAgentPlugin } from "../../src/registry.js";
import { McpToolPool } from "../../src/tool-pool.js";

const manifest = (patch: Partial<AgentManifest> = {}): AgentManifest => ({
  apiVersion: "agent.v1",
  id: "test.host",
  version: "1.0.0",
  displayName: "Host test",
  inputSchema: true,
  outputSchema: true,
  capabilities: ["test.host"],
  requiredPorts: ["model", "tools"],
  toolGrants: [{ toolId: "echo", version: "1", effect: "read" }],
  limits: {
    timeoutMs: 5000,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
    maxEventBytes: 128,
    maxCheckpointBytes: 128,
    maxModelCalls: 1,
    maxToolCalls: 1,
    maxChildRuns: 0,
    maxDepth: 1,
    maxCostUsd: 0.01,
  },
  compatibility: { minHostVersion: "1.0.0" },
  ...patch,
});

function context(options: { reply?: string; agents?: string[]; fail?: boolean } = {}) {
  const pool = new McpToolPool();
  const agents = options.agents ?? ["test.host"];
  const execute = async (input: unknown) => {
    if (options.fail) throw new Error("boom");
    return { echoed: input };
  };
  for (const name of ["echo", "write"])
    pool.register({
      name,
      description: name,
      schema: Type.Any(),
      mutates: false,
      agents,
      authorize: () => true,
      execute,
    });
  const prompts: string[] = [];
  const value = {
    runId: "run-1",
    sessionId: "s",
    userId: "user-1",
    spaceId: "space-1",
    signal: new AbortController().signal,
    tools: pool.forAgent("test.host"),
    pool,
    runtime: {
      prompt: async (input: { system: string }) => {
        prompts.push(input.system);
        return options.reply ?? '{"answer": 42}';
      },
    },
  } as unknown as AgentContext;
  return { value, prompts };
}
const live = () => ({ signal: new AbortController().signal, deadline: Date.now() + 5000 });

describe("host port factory", () => {
  it("binds identity from the host context, not from the agent", () => {
    const scope = hostScope(manifest(), context().value);
    expect(scope).toMatchObject({ actorId: "user-1", workspaceId: "space-1", runId: "run-1" });
    expect(scope.agentId).toBe("test.host");
  });

  it("validates model output against the requested schema and counts calls", async () => {
    const { value, prompts } = context();
    const ports = createHostPorts(manifest(), value);
    const request = {
      profile: "fast",
      prompt: "q",
      outputSchema: { type: "object", required: ["answer"] },
      contextRefs: [],
      idempotencyKey: "k",
    };
    expect(await ports.model.complete(request, live())).toMatchObject({
      status: "ok",
      output: { output: { answer: 42 }, finishReason: "stop" },
    });
    expect((await ports.model.complete(request, live())).status).toBe("denied");
    // Every module call carries the host injection guard in the system prompt.
    expect(prompts[0]).toContain(UNTRUSTED_GUARD);
    const bad = createHostPorts(manifest(), context({ reply: "not json" }).value);
    expect(await bad.model.complete(request, live())).toMatchObject({
      status: "failed",
      error: { code: "model_output_not_json" },
    });
  });

  it("intersects manifest grants with the pool allowlist at the effect boundary", async () => {
    const ports = createHostPorts(manifest(), context().value);
    const call = (toolId: string) =>
      ports.tools.invoke({ toolId, input: { n: 1 }, idempotencyKey: "k1" }, live());
    // "write" is pooled for this agent but not granted by its manifest.
    expect(await call("write")).toMatchObject({
      status: "denied",
      error: { code: "tool_not_granted" },
    });
    expect(await call("echo")).toMatchObject({ status: "ok", output: { echoed: { n: 1 } } });
    const stale = createHostPorts(manifest(), context({ agents: ["someone-else"] }).value);
    expect(
      (await stale.tools.invoke({ toolId: "echo", input: {}, idempotencyKey: "k" }, live())).status,
    ).toBe("denied");
  });

  it("keeps a failed write tool unknown instead of reporting a clean failure", async () => {
    const grants = [{ toolId: "echo", version: "1", effect: "write" as const }];
    const ports = createHostPorts(manifest({ toolGrants: grants }), context({ fail: true }).value);
    expect(
      (await ports.tools.invoke({ toolId: "echo", input: {}, idempotencyKey: "k" }, live())).status,
    ).toBe("unknown");
  });

  it("denies undeclared ports instead of returning empty data", async () => {
    const ports = createHostPorts(manifest({ requiredPorts: [] }), context().value);
    expect(
      (await ports.tools.invoke({ toolId: "echo", input: {}, idempotencyKey: "k" }, live())).status,
    ).toBe("denied");
    expect(await ports.warehouse.catalog(live())).toMatchObject({
      status: "denied",
      error: { code: "port_not_declared" },
    });
  });

  it("returns the cached outcome for a replayed idempotency key without re-executing", async () => {
    const { value } = context();
    let executions = 0;
    value.pool.register({
      name: "count",
      description: "count",
      schema: Type.Any(),
      mutates: true,
      agents: ["test.host"],
      authorize: () => true,
      execute: async () => ++executions,
    });
    const tools = value.pool.forAgent("test.host");
    const grants = [{ toolId: "count", version: "1", effect: "write" as const }];
    const ports = createHostPorts(manifest({ toolGrants: grants }), { ...value, tools });
    const call = () =>
      ports.tools.invoke({ toolId: "count", input: {}, idempotencyKey: "same" }, live());
    expect(await call()).toMatchObject({ status: "ok", output: 1 });
    expect(await call()).toMatchObject({ status: "ok", output: 1 });
    expect(executions).toBe(1);
  });
});

function withTools(value: AgentContext, tools: Record<string, (input: never) => unknown>) {
  for (const [name, execute] of Object.entries(tools)) {
    value.pool.register({
      name,
      description: name,
      schema: Type.Any(),
      mutates: true,
      agents: ["test.host"],
      authorize: () => true,
      execute: async (input) => execute(input as never),
    });
  }
  return { ...value, tools: value.pool.forAgent("test.host") } as AgentContext;
}

describe("memory and collaboration ports", () => {
  const grant = (...ids: string[]) =>
    ids.map((toolId) => ({ toolId, version: "1", effect: "write" as const }));

  it("backs memory with the pool memory tools and marks items untrusted", async () => {
    const notes: Array<{ id: string; key: string | null; text: string; tags: string[] }> = [];
    const value = withTools(context().value, {
      "memory.remember": (input: { key: string; text: string; tags: string[] }) => {
        notes.push({ id: `m${notes.length}`, key: input.key, text: input.text, tags: input.tags });
        return { saved: true };
      },
      "memory.search": () => notes,
      "memory.forget": (input: { id: string }) => ({
        deleted:
          notes.splice(
            notes.findIndex((note) => note.id === input.id || note.key === input.id),
            1,
          ).length === 1,
      }),
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["memory"],
        toolGrants: grant("memory.remember", "memory.search", "memory.forget"),
      }),
      value,
      {
        memoryAudit: {
          async recordAudit(entry) {
            return { ...entry, id: "audit-test", timestamp: new Date().toISOString() };
          },
        },
      },
    );
    const remembered = await ports.memory.remember(
      {
        id: "pref",
        expectedRevision: null,
        content: { lang: "vi" },
        scope: "agent",
        audience: "internal",
        sensitivity: "private",
        expiresAt: null,
        provenance: [],
        idempotencyKey: "r1",
      },
      live(),
    );
    expect(remembered).toMatchObject({ status: "ok", output: { id: "pref", trust: "untrusted" } });
    const found = await ports.memory.search(
      { query: "lang", scope: "agent", limit: 5, maxBytes: 4096, asOf: new Date().toISOString() },
      live(),
    );
    expect(found).toMatchObject({
      status: "ok",
      output: [{ id: "pref", content: { lang: "vi" }, sensitivity: "private" }],
    });
    expect(
      (
        await ports.memory.forget(
          { id: "pref", expectedRevision: "1", idempotencyKey: "f1" },
          live(),
        )
      ).status,
    ).toBe("ok");
    expect(notes).toEqual([]);
    const ungranted = createHostPorts(manifest({ requiredPorts: ["memory"] }), value);
    expect(
      await ungranted.memory.search(
        { query: "x", scope: "agent", limit: 1, maxBytes: 100, asOf: new Date().toISOString() },
        live(),
      ),
    ).toMatchObject({ status: "denied", error: { code: "memory_not_granted" } });
  });

  it("uses the injected durable audit writer and preserves expiry metadata", async () => {
    const notes: Array<{ id: string; key: string | null; text: string; tags: string[] }> = [];
    const audits: Array<{ operation: string; resource: string }> = [];
    const value = withTools(context().value, {
      "memory.remember": (input: { key: string; text: string; tags: string[] }) => {
        notes.push({ id: input.key, key: input.key, text: input.text, tags: input.tags });
        return { saved: true };
      },
      "memory.search": () => notes,
      "memory.forget": () => ({ deleted: true }),
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["memory"],
        toolGrants: grant("memory.remember", "memory.search", "memory.forget"),
      }),
      value,
      {
        memoryAudit: {
          async recordAudit(entry) {
            audits.push({ operation: entry.operation, resource: entry.resource });
            return { ...entry, id: "audit-1", timestamp: new Date().toISOString() };
          },
        },
      },
    );
    const expiresAt = new Date(Date.now() + 60_000).toISOString();
    const result = await ports.memory.remember(
      {
        id: "expiring",
        expectedRevision: null,
        content: "temporary",
        scope: "agent",
        audience: "internal",
        sensitivity: "private",
        expiresAt,
        provenance: [],
        idempotencyKey: "remember-expiring",
      },
      live(),
    );
    expect(result).toMatchObject({ status: "ok", output: { expiresAt } });
    expect(audits).toEqual([{ operation: "commit", resource: "expiring" }]);
  });

  it("fails closed on memory mutation when no audit writer is configured", async () => {
    const value = withTools(context().value, {
      "memory.remember": () => ({ saved: true }),
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["memory"],
        toolGrants: grant("memory.remember"),
      }),
      value,
    );
    const result = await ports.memory.remember(
      {
        id: "no-audit",
        expectedRevision: null,
        content: "note",
        scope: "agent",
        audience: "internal",
        sensitivity: "private",
        expiresAt: null,
        provenance: [],
        idempotencyKey: "remember-no-audit",
      },
      live(),
    );
    expect(result).toMatchObject({
      status: "failed",
      error: { code: "memory_audit_unavailable" },
    });
  });

  it("deletes memory by exact public key without requiring search permission", async () => {
    const callIds: string[] = [];
    const value = withTools(context().value, {
      "memory.forget": (input: { id: string }) => {
        callIds.push(input.id);
        return { deleted: input.id === "public-note-key" };
      },
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["memory"],
        toolGrants: grant("memory.forget"),
      }),
      value,
      {
        memoryAudit: {
          async recordAudit(entry) {
            return { ...entry, id: "audit-test", timestamp: new Date().toISOString() };
          },
        },
      },
    );
    const result = await ports.memory.forget(
      { id: "public-note-key", expectedRevision: "1", idempotencyKey: "forget-public" },
      live(),
    );
    expect(result).toMatchObject({ status: "ok", output: { deleted: true } });
    expect(callIds).toEqual(["public-note-key"]);
  });

  it("delegates through agents.delegate and tracks child results", async () => {
    const messages: unknown[] = [];
    const value = withTools(context().value, {
      "agents.delegate": (input: { agent: string; message: string }) => {
        messages.push(input);
        return input.agent === "bad" ? "error: nope" : `done:${input.message}`;
      },
    });
    value.catalog = {
      findByCapability: () => [
        { id: "data", version: "1.0.0", description: "d", capabilities: ["warehouse.query"] },
        { id: "test.host", version: "1.0.0", description: "self", capabilities: ["x"] },
      ],
    };
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["collaboration"],
        toolGrants: grant("agents.delegate"),
        limits: { ...manifest().limits, maxChildRuns: 2 },
      }),
      value,
    );
    expect(await ports.collaboration.discover({ capability: "*", limit: 5 }, live())).toMatchObject(
      {
        status: "ok",
        output: [{ agentId: "data" }],
      },
    );
    const invoke = (agentId: string, key: string) =>
      ports.collaboration.invoke(
        { agentId, version: "1.0.0", input: "hi", idempotencyKey: key },
        live(),
      );
    const ok = await invoke("data", "k1");
    const bad = await invoke("bad", "k2");
    if (ok.status !== "ok" || bad.status !== "ok") throw new Error("invoke failed");
    expect((await invoke("data", "k1")).status).toBe("ok"); // replay: no third child
    expect((await invoke("data", "k3")).status).toBe("denied"); // maxChildRuns
    const runIds = [ok.output.runId, bad.output.runId];
    expect(await ports.collaboration.wait({ runIds }, live())).toMatchObject({
      output: { completedRunIds: runIds },
    });
    expect(await ports.collaboration.result({ runId: runIds[0] }, live())).toMatchObject({
      output: { status: "completed", output: "done:hi" },
    });
    expect(await ports.collaboration.result({ runId: runIds[1] }, live())).toMatchObject({
      output: { status: "failed" },
    });
    expect(messages).toHaveLength(2);
  });
});

describe("warehouse, artifact and tool backoff ports", () => {
  const grant = (...ids: string[]) =>
    ids.map((toolId) => ({ toolId, version: "1", effect: "write" as const }));

  it("maps warehouse tools to catalog, describe and a byte-bounded query", async () => {
    const value = withTools(context().value, {
      "warehouse.list_sources": () => ({ warehouses: [{ id: "demo", name: "Demo" }] }),
      "warehouse.list_tables": () => ({ tables: [{ name: "sales" }] }),
      "warehouse.describe_table": () => ({
        table: { columns: [{ name: "region", type: "text", nullable: false }] },
      }),
      "warehouse.run_query": () => ({
        row_count: 3,
        preview: [{ region: "North" }, { region: "South" }, { region: "East" }],
      }),
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["warehouse"],
        toolGrants: grant(
          "warehouse.list_sources",
          "warehouse.list_tables",
          "warehouse.describe_table",
          "warehouse.run_query",
        ),
      }),
      value,
    );
    expect(await ports.warehouse.catalog(live())).toMatchObject({
      status: "ok",
      output: [{ id: "demo/sales", displayName: "Demo: sales" }],
    });
    expect(
      await ports.warehouse.describe({ sourceId: "demo", datasetId: "demo/sales" }, live()),
    ).toMatchObject({ status: "ok", output: { columns: [{ name: "region", type: "text" }] } });
    const queried = await ports.warehouse.query(
      { queryId: "demo/sales", parameters: {}, maxRows: 2, maxBytes: 4096, idempotencyKey: "q1" },
      live(),
    );
    expect(queried).toMatchObject({
      status: "ok",
      output: { rows: [{ region: "North" }, { region: "South" }], truncated: true },
    });
    const ungranted = createHostPorts(manifest({ requiredPorts: ["warehouse"] }), value);
    expect(await ungranted.warehouse.catalog(live())).toMatchObject({
      status: "denied",
      error: { code: "warehouse_not_granted" },
    });
  });

  it("commits artifacts only after length and SHA-256 match, then reads slices", async () => {
    const stored = new Map<string, string>();
    const value = withTools(context().value, {
      "artifacts.store": (input: { bytesBase64: string }) => {
        const bytes = Buffer.from(input.bytesBase64, "base64");
        stored.set("a1", input.bytesBase64);
        return {
          id: "a1",
          sha256: createHash("sha256").update(bytes).digest("hex"),
          bytes: bytes.byteLength,
        };
      },
      "artifacts.read": (input: { artifactId: string }) => {
        const data = stored.get(input.artifactId);
        return data
          ? {
              found: true,
              artifact: { id: "a1", status: "ready", bytes: 5 },
              bytesBase64: data,
            }
          : { found: false };
      },
    });
    const ports = createHostPorts(
      manifest({
        requiredPorts: ["artifacts"],
        toolGrants: grant("artifacts.store", "artifacts.read"),
      }),
      value,
    );
    const content = Buffer.from("hello");
    const begin = (key: string, sha256: string) =>
      ports.artifacts.begin(
        {
          kind: "report",
          version: "1",
          mediaType: "text/plain",
          expectedBytes: content.byteLength,
          expectedSha256: sha256,
          idempotencyKey: key,
        },
        live(),
      );
    const upload = async (key: string, sha256: string) => {
      const started = await begin(key, sha256);
      if (started.status !== "ok") throw new Error("begin failed");
      const { uploadId } = started.output;
      await ports.artifacts.write(
        { uploadId, offset: 0, bytes: new Uint8Array(content), idempotencyKey: `${key}.w` },
        live(),
      );
      return ports.artifacts.commit({ uploadId, idempotencyKey: key }, live());
    };
    expect(await upload("bad", "0".repeat(64))).toMatchObject({
      status: "failed",
      error: { code: "artifact_hash_mismatch" },
    });
    expect(stored.size).toBe(0);
    const sha = createHash("sha256").update(content).digest("hex");
    expect(await upload("good", sha)).toMatchObject({
      status: "ok",
      output: { id: "a1", status: "ready", sha256: sha, bytes: 5 },
    });
    const read = await ports.artifacts.read({ artifactId: "a1", offset: 1, maxBytes: 2 }, live());
    expect(read).toMatchObject({ status: "ok", output: { nextOffset: 3 } });
    if (read.status === "ok") expect(Buffer.from(read.output.bytes).toString()).toBe("el");
  });

  it("backs off a failing tool instead of retrying it immediately", async () => {
    let calls = 0;
    const value = withTools(context().value, {
      flaky: () => {
        calls++;
        throw new Error("down");
      },
    });
    const ports = createHostPorts(
      manifest({ toolGrants: [{ toolId: "flaky", version: "1", effect: "read" }] }),
      value,
    );
    const call = (key: string) =>
      ports.tools.invoke({ toolId: "flaky", input: {}, idempotencyKey: key }, live());
    expect((await call("k1")).status).toBe("failed");
    expect(await call("k2")).toMatchObject({ error: { code: "tool_backoff" } });
    expect(calls).toBe(1);
  });
});

/** Minimal code-only agent.v1 modules; the product roster itself is Python (agents/). */
const codeModule = (id: string): AgentModule<JsonValue, JsonValue> => ({
  manifest: manifest({
    id,
    inputSchema: {
      type: "object",
      required: ["numbers"],
      properties: { numbers: { type: "array", items: { type: "number" }, minItems: 1 } },
    },
    outputSchema: {
      type: "object",
      required: ["mean"],
      properties: { mean: { type: "number" } },
    },
    capabilities: ["math.statistics"],
    requiredPorts: [],
    toolGrants: [],
    limits: { ...manifest().limits, maxModelCalls: 0, maxToolCalls: 0 },
  }),
  async execute(ctx) {
    const numbers = (ctx.input as { numbers: number[] }).numbers;
    return {
      status: "completed",
      output: { mean: numbers.reduce((a, b) => a + b, 0) / numbers.length },
      artifacts: [],
      evidence: [],
      warnings: [],
      usage: {
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheWriteTokens: 0,
        modelCalls: 0,
        toolCalls: 0,
        durationMs: 0,
        estimatedCostUsd: 0,
      },
    };
  },
});
const agentModules = [codeModule("reference.statistics"), codeModule("template.classifier")];

describe("agent.v1 modules in the production pool", () => {
  it("runs a module through the plugin contract with output validation", async () => {
    const plugin = moduleAsPlugin(agentModules[0]);
    expect(plugin.descriptor).toMatchObject({
      id: "reference.statistics",
      acceptsDelegation: false,
    });
    expect(await plugin.run({ numbers: [1, 2, 3] }, context().value)).toMatchObject({ mean: 2 });
  });

  it("fails registration for modules needing ports production cannot provide", () => {
    const needsUnsupported = {
      manifest: manifest({ requiredPorts: ["fictional" as never] }),
      execute: async () => ({}),
    };
    expect(() => moduleAsPlugin(needsUnsupported as never)).toThrow(/not wired/);
  });

  it("serves only enabled versions and rejects unsupported canary", async () => {
    const served = await activeModulePlugins(agentModules, {
      "reference.statistics": "enabled",
      "template.classifier": "disabled",
    });
    expect(served.map((plugin) => plugin.descriptor.id)).toEqual(["reference.statistics"]);
    await expect(
      activeModulePlugins(agentModules, { "reference.statistics": "canary" }),
    ).rejects.toThrow(/canary/);
  });
});

describe("process protocol v2 through the same factory", () => {
  it("bridges port calls from a Python v2 agent to granted pool tools only", async () => {
    const script = join(tmpdir(), `v2_agent_${process.pid}.py`);
    writeFileSync(
      script,
      [
        "import sys",
        "sys.path.insert(0, 'sdk/python')",
        "from agent_platform import serve",
        "class Agent:",
        "    def run(self, value, ctx):",
        "        echoed = ctx.tools.call('echo', {'n': value['n']})",
        "        try:",
        "            ctx.tools.call('write', {})",
        "            denied = False",
        "        except RuntimeError:",
        "            denied = True",
        "        return {'echoed': echoed, 'write_denied': denied}",
        "serve(Agent())",
      ].join("\n"),
    );
    const plugin = createExternalAgentPlugin({
      id: "test.host",
      version: "1.0.0",
      name: "v2",
      description: "v2 bridge",
      protocol: "agent-runner.v2",
      tools: ["echo"],
      inputSchema: { type: "object" },
      command: "python3",
      args: [script],
    });
    expect(await plugin.run({ n: 7 }, context().value)).toEqual({
      echoed: { echoed: { n: 7 } },
      write_denied: true,
    });
  });
});
