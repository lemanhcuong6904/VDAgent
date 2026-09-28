import type { AgentEvent } from "./generated/agent-event.js";
import type { AgentManifest } from "./generated/agent-manifest.js";
import type { AgentResultWire } from "./generated/agent-result.js";
import type { AgentScope } from "./generated/agent-scope.js";
import type { CheckpointRef } from "./generated/checkpoint-ref.js";
import type { WaitRequest } from "./generated/wait-request.js";
import type { AgentPorts, JsonValue } from "./ports.js";

export type ToolGrant = AgentManifest["toolGrants"][number];
export type AgentResult<O extends JsonValue> =
  | (Omit<Extract<AgentResultWire, { status: "completed" }>, "output"> & { output: O })
  | Exclude<AgentResultWire, { status: "completed" }>;
export interface AgentExecutionContext<I extends JsonValue> {
  readonly input: I;
  readonly scope: Readonly<AgentScope>;
  readonly ports: AgentPorts;
  readonly signal: AbortSignal;
  readonly deadline: number;
  emit(event: AgentEvent): Promise<void>;
  checkpoint(state: JsonValue): Promise<CheckpointRef>;
  /** Host suspends execution durably; successful wait never resumes this invocation. */
  wait(reason: WaitRequest): Promise<never>;
}
export interface AgentModule<I extends JsonValue, O extends JsonValue> {
  readonly manifest: AgentManifest;
  execute(context: AgentExecutionContext<I>): Promise<AgentResult<O>>;
}
