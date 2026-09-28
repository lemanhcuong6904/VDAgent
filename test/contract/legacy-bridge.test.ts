import { Type } from "typebox";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentContext, AgentPlugin } from "../../src/agent-contract.js";
import type { AgentExecutionContext, AgentPorts, JsonValue } from "../../src/contracts/index.js";
import { createPorts } from "../../src/ports/index.js";
import { LegacyAgentAdapter, LegacyAgentRegistry } from "../../src/ports/legacy-bridge.js";
import { contractTestKit } from "../../src/testkit/contract-validator.js";
import { McpToolPool } from "../../src/tool-pool.js";

function fixture() {
  const manifest = contractTestKit.createMinimalManifest({ id: "legacy" });
  const run = vi.fn<AgentPlugin["run"]>(async (input) => input);
  const plugin: AgentPlugin = {
    descriptor: {
      id: "legacy",
      version: "1.0.0",
      name: "Legacy",
      description: "Fixture",
      input: Type.Object({}),
      tools: [],
    },
    run,
  };
  const unused = async (): Promise<never> => {
    throw new Error("Unexpected port access");
  };
  const ports = createPorts({
    model: { complete: unused },
    tools: { invoke: unused },
    warehouse: { catalog: unused, describe: unused, query: unused },
    artifacts: { begin: unused, write: unused, commit: unused, read: unused },
    memory: { read: unused, search: unused, remember: unused, forget: unused },
    collaboration: { discover: unused, invoke: unused, wait: unused, result: unused },
  });
  const controller = new AbortController();
  const ctx: AgentExecutionContext<JsonValue> = {
    input: { value: 3 },
    ports,
    signal: controller.signal,
    deadline: Date.now() + 1000,
    scope: {
      tenantId: "t",
      actorId: "u",
      workspaceId: "w",
      audience: "private",
      taskId: "task",
      runId: "run",
      attemptId: "attempt",
      agentId: "legacy",
      agentVersion: "1.0.0",
      policyRevision: "p1",
      fence: "1",
      traceId: "trace",
    },
    emit: unused,
    checkpoint: unused,
    wait: unused,
  };
  const legacy: AgentContext = {
    runId: "run",
    sessionId: "session",
    userId: "u",
    spaceId: "w",
    signal: ctx.signal,
    tools: [],
    pool: new McpToolPool(),
    runtime: { prompt: unused },
  };
  const factory = vi.fn(() => legacy);
  return { manifest, plugin, run, ctx, legacy, factory, controller, ports };
}

afterEach(() => vi.useRealTimers());
describe("legacy bridge using the real AgentPlugin interface", () => {
  it("preserves domain output and injects host dependencies through run(input, context)", async () => {
    const f = fixture();
    const result = await new LegacyAgentAdapter(f.plugin, f.manifest, f.factory).execute(f.ctx);
    expect(result).toMatchObject({ status: "completed", output: f.ctx.input, evidence: [] });
    expect(f.run).toHaveBeenCalledWith(
      f.ctx.input,
      expect.objectContaining({ pool: f.legacy.pool }),
    );
    contractTestKit.expectValidResult(result);
  });
  it("propagates failure without manufacturing a successful result", async () => {
    const f = fixture();
    f.run.mockRejectedValue(new Error("legacy failed"));
    await expect(
      new LegacyAgentAdapter(f.plugin, f.manifest, f.factory).execute(f.ctx),
    ).rejects.toThrow("legacy failed");
  });
  it("rejects scope mismatch before execution", async () => {
    const f = fixture();
    f.legacy.spaceId = "another-workspace";
    await expect(
      new LegacyAgentAdapter(f.plugin, f.manifest, f.factory).execute(f.ctx),
    ).rejects.toThrow("identity mismatch");
    expect(f.run).not.toHaveBeenCalled();
  });
  it("rejects expired and cancelled calls before acquiring host context", async () => {
    const f = fixture();
    const adapter = new LegacyAgentAdapter(f.plugin, f.manifest, f.factory);
    await expect(adapter.execute({ ...f.ctx, deadline: 0 })).rejects.toThrow("deadline");
    f.controller.abort(new Error("cancelled"));
    await expect(adapter.execute(f.ctx)).rejects.toThrow("cancelled");
    expect(f.factory).not.toHaveBeenCalled();
  });
  it("aborts a running legacy call on deadline and clears the timer", async () => {
    vi.useFakeTimers();
    const f = fixture();
    let signal: AbortSignal | undefined;
    f.run.mockImplementation(async (_, context) => {
      signal = context.signal;
      return new Promise(() => {});
    });
    const result = new LegacyAgentAdapter(f.plugin, f.manifest, f.factory).execute(f.ctx);
    const assertion = expect(result).rejects.toThrow("deadline");
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
    expect(signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("rejects non-JSON and schema-invalid outputs", async () => {
    const f = fixture();
    const adapter = new LegacyAgentAdapter(f.plugin, f.manifest, f.factory);
    f.run.mockResolvedValue(undefined);
    await expect(adapter.execute(f.ctx)).rejects.toThrow();
    f.run.mockResolvedValue("not an object");
    await expect(adapter.execute(f.ctx)).rejects.toThrow("Invalid agent output");
  });
  it("registers real plugins and rejects duplicate registrations", () => {
    const f = fixture();
    const registry = new LegacyAgentRegistry();
    registry.register("legacy", f.plugin, f.manifest, f.factory);
    expect(registry.get("legacy")).toBeInstanceOf(LegacyAgentAdapter);
    expect(registry.list()[0].manifest.id).toBe("legacy");
    expect(() => registry.register("legacy", f.plugin, f.manifest, f.factory)).toThrow("duplicate");
  });
  it("requires complete public ports and freezes the assembled container", () => {
    expect(Object.isFrozen(fixture().ports)).toBe(true);
    expect(() => createPorts({} as AgentPorts)).toThrow("Missing host port");
  });
});
