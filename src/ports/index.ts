/**
 * Ports
 * Public interfaces for agent execution context
 */

export * from "./mcp-adapter.js";
export * from "./tool-pool.js";
export * from "./tool-port.js";
export * from "./tools/file-reader.js";
export * from "./tools/file-writer.js";

import type { AgentPorts } from "../contracts/index.js";

/** Assemble host-bound ports; provider construction and authorization belong to the host. */
export function createPorts(config: AgentPorts): Readonly<AgentPorts> {
  for (const [name, methods] of Object.entries({
    model: ["complete"],
    tools: ["invoke"],
    warehouse: ["catalog", "describe", "query"],
    artifacts: ["begin", "write", "commit", "read"],
    memory: ["read", "search", "remember", "forget"],
    collaboration: ["discover", "invoke", "wait", "result"],
  })) {
    const port = config[name as keyof AgentPorts];
    if (!port || methods.some((method) => typeof Reflect.get(port, method) !== "function"))
      throw new Error(`Missing host port: ${name}`);
  }
  const sandbox = config.sandbox;
  if (
    sandbox &&
    ["execute", "pause", "resume"].some(
      (method) => typeof Reflect.get(sandbox, method) !== "function",
    )
  )
    throw new Error("Invalid sandbox port");
  return Object.freeze({ ...config });
}
