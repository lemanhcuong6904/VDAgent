/**
 * Agent Protocol v2
 * Versioned bidirectional JSONL protocol for agent process communication
 */

export const AGENT_PROTOCOL = "agent-runner.v2" as const;

// Core protocol types
export interface AgentScope {
  user_id: string;
  space_id: string;
  task_id?: string;
  run_id?: string;
  parent_run_id?: string;
  trace_id?: string;
}

export interface StructuredError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  retriable?: boolean;
}

export interface UsageSummary {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

export interface ArtifactRef {
  id: string;
  type: string;
  url?: string;
  metadata?: Record<string, unknown>;
}

export interface CheckpointManifest {
  id: string;
  created_at: string;
  parent_id?: string;
  base_id?: string;
  source?: string;
  content_hash?: string;
  size_bytes?: number;
  metadata?: Record<string, unknown>;
}

// Protocol messages (host -> agent)
export interface HelloMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "hello";
  version: string;
  capabilities: readonly string[];
  metadata?: Record<string, unknown>;
}

export interface InvokeMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "invoke";
  request_id: string;
  agent_id: string;
  agent_version?: string;
  input: unknown;
  scope: AgentScope;
  tools?: readonly string[];
  deadline_at?: string;
  checkpoint_id?: string;
  idempotency_key?: string;
}

export interface PortResultMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "port_result";
  request_id: string;
  call_id: string;
  ok: boolean;
  output?: unknown;
  error?: StructuredError;
  sequence?: number;
}

export interface CancelMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "cancel";
  request_id: string;
  reason?: string;
}

// Protocol messages (agent -> host)
export interface PortCallMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "port_call";
  request_id: string;
  call_id: string;
  port: string;
  operation: string;
  input?: unknown;
  sequence?: number;
  idempotency_key?: string;
}

export interface EventMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "event";
  request_id: string;
  event: string;
  data?: unknown;
  timestamp?: string;
}

export interface CheckpointMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "checkpoint";
  request_id: string;
  checkpoint_id: string;
  manifest?: CheckpointManifest;
  parent_id?: string;
}

export interface WaitMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "wait";
  request_id: string;
  wait_for: string;
  timeout_ms?: number;
  poll_interval_ms?: number;
}

export interface ResultMessage {
  protocol: typeof AGENT_PROTOCOL;
  type: "result";
  request_id: string;
  ok: boolean;
  output?: unknown;
  error?: StructuredError;
  usage?: UsageSummary;
  artifacts?: readonly ArtifactRef[];
}

export type HostMessage = HelloMessage | InvokeMessage | PortResultMessage | CancelMessage;
export type AgentMessage =
  | PortCallMessage
  | EventMessage
  | CheckpointMessage
  | WaitMessage
  | ResultMessage;
export type ProtocolMessage = HostMessage | AgentMessage;

// Type guards
export function isProtocolMessage(value: unknown): value is ProtocolMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    "protocol" in value &&
    value.protocol === AGENT_PROTOCOL &&
    "type" in value &&
    typeof value.type === "string"
  );
}

export function isHostMessage(message: ProtocolMessage): message is HostMessage {
  return (
    message.type === "hello" ||
    message.type === "invoke" ||
    message.type === "port_result" ||
    message.type === "cancel"
  );
}

export function isAgentMessage(message: ProtocolMessage): message is AgentMessage {
  return (
    message.type === "port_call" ||
    message.type === "event" ||
    message.type === "checkpoint" ||
    message.type === "wait" ||
    message.type === "result"
  );
}

// Forward compatibility: preserve unknown fields
export function parseMessage(line: string): ProtocolMessage {
  const parsed = JSON.parse(line);
  if (!isProtocolMessage(parsed)) {
    throw new Error("Invalid protocol v2 message");
  }
  return parsed;
}

export function serializeMessage(message: ProtocolMessage): string {
  return JSON.stringify(message);
}
