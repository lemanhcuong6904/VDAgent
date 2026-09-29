import type { EvidenceRef } from "./generated/evidence-ref.js";
import type { PortCallWire } from "./generated/port-call.js";
import type { PortResultWire } from "./generated/port-result.js";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
/** Schema document; the host validates dialect, references and byte/depth limits. */
export type JsonSchema = boolean | { [key: string]: JsonValue };
/** Identity is bound by the host factory, never accepted as an agent-supplied option. */
export interface CallOptions {
  signal: AbortSignal;
  deadline: number;
}
export type PortOutcome<T> =
  | { status: "ok"; output: T; evidence: EvidenceRef[]; limitations: string[] }
  | Exclude<Extract<PortResultWire, { method: "tools.invoke" }>["outcome"], { status: "ok" }>;

/** Data declarations derive from canonical wire schemas; signals and bytes remain local. */
export type PortMethod = PortCallWire["method"];
export type PortInput<M extends PortMethod> = Extract<PortCallWire, { method: M }>["input"];
export type PortOutput<M extends PortMethod> = Extract<
  Extract<PortResultWire, { method: M }>["outcome"],
  { status: "ok" }
>["output"];
type LocalResult<M extends PortMethod> = Promise<PortOutcome<PortOutput<M>>>;

export interface ModelPort {
  complete(input: PortInput<"model.complete">, options: CallOptions): LocalResult<"model.complete">;
}
export interface ToolPort {
  invoke(input: PortInput<"tools.invoke">, options: CallOptions): LocalResult<"tools.invoke">;
}
export interface WarehousePort {
  catalog(options: CallOptions): LocalResult<"warehouse.catalog">;
  describe(
    input: PortInput<"warehouse.describe">,
    options: CallOptions,
  ): LocalResult<"warehouse.describe">;
  /** Host-registered query identity; no raw SQL or arbitrary provider URI. */
  query(input: PortInput<"warehouse.query">, options: CallOptions): LocalResult<"warehouse.query">;
}
export interface ArtifactPort {
  begin(input: PortInput<"artifacts.begin">, options: CallOptions): LocalResult<"artifacts.begin">;
  write(
    input: Omit<PortInput<"artifacts.write">, "bytesBase64"> & { bytes: Uint8Array },
    options: CallOptions,
  ): LocalResult<"artifacts.write">;
  /** Host verifies stored bytes before returning a ready reference. */
  commit(
    input: PortInput<"artifacts.commit">,
    options: CallOptions,
  ): LocalResult<"artifacts.commit">;
  read(
    input: PortInput<"artifacts.read">,
    options: CallOptions,
  ): Promise<
    PortOutcome<Omit<PortOutput<"artifacts.read">, "bytesBase64"> & { bytes: Uint8Array }>
  >;
}
export type MemoryItem = NonNullable<PortOutput<"memory.read">>;
export interface MemoryPort {
  read(input: PortInput<"memory.read">, options: CallOptions): LocalResult<"memory.read">;
  search(input: PortInput<"memory.search">, options: CallOptions): LocalResult<"memory.search">;
  remember(
    input: PortInput<"memory.remember">,
    options: CallOptions,
  ): LocalResult<"memory.remember">;
  forget(input: PortInput<"memory.forget">, options: CallOptions): LocalResult<"memory.forget">;
}
export interface CollaborationPort {
  discover(
    input: PortInput<"collaboration.discover">,
    options: CallOptions,
  ): LocalResult<"collaboration.discover">;
  invoke(
    input: PortInput<"collaboration.invoke">,
    options: CallOptions,
  ): LocalResult<"collaboration.invoke">;
  wait(
    input: PortInput<"collaboration.wait">,
    options: CallOptions,
  ): LocalResult<"collaboration.wait">;
  result(
    input: PortInput<"collaboration.result">,
    options: CallOptions,
  ): LocalResult<"collaboration.result">;
}
export interface SandboxPort {
  execute(
    input: PortInput<"sandbox.execute">,
    options: CallOptions,
  ): LocalResult<"sandbox.execute">;
  pause(input: PortInput<"sandbox.pause">, options: CallOptions): LocalResult<"sandbox.pause">;
  resume(input: PortInput<"sandbox.resume">, options: CallOptions): LocalResult<"sandbox.resume">;
}
export interface AgentPorts {
  model: ModelPort;
  tools: ToolPort;
  warehouse: WarehousePort;
  artifacts: ArtifactPort;
  memory: MemoryPort;
  collaboration: CollaborationPort;
  sandbox?: SandboxPort;
}
