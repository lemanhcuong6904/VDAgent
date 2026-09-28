/**
 * Runs a canonical AgentModule (agent.v1) inside the production AgentPool. Ports come from the
 * shared host factory; registration fails closed when a module needs a port production cannot
 * provide yet. Checkpoint/wait need the durable workflow host and are rejected explicitly here.
 */
import { Ajv2020 } from "ajv/dist/2020.js";
import { Type } from "typebox";
import type { AgentContext, AgentPlugin } from "../agent-contract.js";
import type { AgentModule, JsonValue } from "../contracts/index.js";
import {
  createHostPorts,
  type HostPortDependencies,
  hostScope,
  WIRED_PORTS,
} from "./host-factory.js";

export function moduleAsPlugin(
  module: AgentModule<JsonValue, JsonValue>,
  dependencies: HostPortDependencies = {},
): AgentPlugin {
  const { manifest } = module;
  const missing = manifest.requiredPorts.filter(
    (port) => !(WIRED_PORTS as readonly string[]).includes(port),
  );
  if (missing.length)
    throw new Error(
      `Agent module '${manifest.id}' requires ports not wired in production: ${missing.join(", ")}`,
    );
  const validateOutput = new Ajv2020({ strict: false, addUsedSchema: false }).compile(
    manifest.outputSchema as object,
  );
  return {
    descriptor: {
      apiVersion: "agent-plugin.v2",
      id: manifest.id,
      version: manifest.version,
      name: manifest.displayName,
      description: manifest.displayName,
      capabilities: manifest.capabilities,
      modelProfile: manifest.modelProfile,
      // Typed modules do not take the free-text delegation prompt.
      acceptsDelegation: false,
      // The legacy pool treats limits as positive caps; a 0 (e.g. no tools) is enforced by the port.
      limits: {
        ...(manifest.limits.maxToolCalls > 0 ? { maxToolCalls: manifest.limits.maxToolCalls } : {}),
        maxDurationMs: manifest.limits.timeoutMs,
      },
      input: Type.Unsafe(manifest.inputSchema as object),
      output: Type.Unsafe(manifest.outputSchema as object),
      tools: manifest.toolGrants.map((grant) => grant.toolId),
    },
    async run(input: unknown, context: AgentContext) {
      if (
        new TextEncoder().encode(JSON.stringify(input)).byteLength > manifest.limits.maxInputBytes
      )
        throw new Error("Agent input exceeds manifest limit");
      const timeout = AbortSignal.timeout(manifest.limits.timeoutMs);
      const signal = AbortSignal.any([context.signal, timeout]);
      const result = await module.execute({
        input: structuredClone(input) as JsonValue,
        scope: Object.freeze(hostScope(manifest, context)),
        ports: Object.freeze(createHostPorts(manifest, context, dependencies)),
        signal,
        deadline: Date.now() + manifest.limits.timeoutMs,
        // Events are not forwarded to user streams until the event contract is wired.
        emit: async () => undefined,
        checkpoint: async () => {
          throw new Error("Checkpoints require the durable workflow host");
        },
        wait: async () => {
          throw new Error("Durable wait requires the durable workflow host");
        },
      });
      // Waiting/approval states need the durable workflow host; never report them as output.
      if (result.status !== "completed")
        throw new Error(`Agent '${manifest.id}' returned ${result.status}; needs the durable host`);
      if (!validateOutput(result.output)) throw new Error("Agent output violates its manifest");
      if (
        new TextEncoder().encode(JSON.stringify(result.output)).byteLength >
        manifest.limits.maxOutputBytes
      )
        throw new Error("Agent output exceeds manifest limit");
      return result.output;
    },
  };
}
