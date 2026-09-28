/**
 * Tool Port Interface
 * Standardized tool invocation with effect class, idempotency, and grants
 */

import type { AgentScope } from "../contracts/index.js";

export type EffectClass = "read" | "write" | "delete" | "execute" | "network" | "sensitive";

export interface ToolManifest {
  id: string;
  version: string;
  displayName: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  effectClass: EffectClass;
  idempotent: boolean;
  compensation?: string; // Tool ID for compensating action
  limits: {
    maxInputBytes: number;
    maxOutputBytes: number;
    timeoutMs: number;
  };
  sensitivity: "public" | "internal" | "confidential" | "restricted";
  tags?: string[];
}

export interface ToolContext {
  runId: string;
  attemptId: string;
  scope: AgentScope;
  idempotencyKey?: string;
  deadline: number;
  fence: string;
}

export interface ToolInvocation<I = unknown> {
  toolId: string;
  version?: string;
  input: I;
  context: ToolContext;
}

export interface ToolResult<O = unknown> {
  status: "success" | "error" | "timeout" | "unknown";
  output?: O;
  error?: ToolError;
  evidence?: EvidenceRef[];
  limitations?: string[];
  usage?: {
    durationMs: number;
    bytesRead?: number;
    bytesWritten?: number;
  };
}

export interface ToolError {
  code: string;
  message: string;
  class: "validation" | "permission" | "transient" | "permanent" | "unknown";
  retryable: boolean;
  safeMessage: string;
}

export interface EvidenceRef {
  type: "receipt" | "claim" | "observer_hint" | "process_exit";
  id: string;
  timestamp: string;
  verified: boolean;
}

/**
 * Tool Port - injected into agent execution context
 */
export interface ToolPort {
  /**
   * Invoke a tool with granted access
   */
  invoke<I, O>(invocation: ToolInvocation<I>): Promise<ToolResult<O>>;

  /**
   * Check if tool is available and granted
   */
  available(toolId: string, version?: string): Promise<boolean>;

  /**
   * Get tool manifest
   */
  getManifest(toolId: string, version?: string): Promise<ToolManifest | undefined>;
}
