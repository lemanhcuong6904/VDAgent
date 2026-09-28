/**
 * Tool Pool
 * Manages tool registration, grants, and invocation with effect tracking
 */

import type { AgentScope } from "../contracts/index.js";
import type {
  ToolContext,
  ToolError,
  ToolInvocation,
  ToolManifest,
  ToolPort,
  ToolResult,
} from "./tool-port.js";

export type ToolHandler<I = unknown, O = unknown> = (input: I, context: ToolContext) => Promise<O>;

function idempotencyIdentity(toolId: string, key: string, context: ToolContext): string {
  return JSON.stringify([
    context.scope.tenantId,
    context.scope.workspaceId,
    context.scope.actorId,
    context.runId,
    toolId,
    key,
  ]);
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`)
    .join(",")}}`;
}

function idempotencyConflict<T extends ToolResult>(): T {
  return {
    status: "error",
    error: {
      code: "idempotency_conflict",
      message: "Idempotency key was already used with different input",
      class: "validation",
      retryable: false,
      safeMessage: "Idempotency key conflict",
    },
  } as T;
}

export interface ToolRegistration<I = unknown, O = unknown> {
  manifest: ToolManifest;
  handler: ToolHandler<I, O>;
  registeredAt: string;
  registeredBy: string;
}

export interface ToolExecution {
  id: string;
  toolId: string;
  version: string;
  runId: string;
  attemptId: string;
  scope: AgentScope;
  idempotencyKey?: string;
  startedAt: string;
  completedAt?: string;
  status: "running" | "success" | "error" | "timeout" | "unknown";
  durationMs?: number;
  input: unknown;
  output?: unknown;
  error?: ToolError;
}

export class ToolPool {
  private tools = new Map<string, Map<string, ToolRegistration>>();
  private executions = new Map<string, ToolExecution[]>(); // runId -> executions
  private readonly idempotencyCache = new Map<
    string,
    { inputHash: string; result: ToolResult; expiresAt: number }
  >();
  private readonly idempotencyInFlight = new Map<
    string,
    { inputHash: string; result: Promise<ToolResult> }
  >();
  private readonly maxIdempotencyEntries = 10_000;
  private readonly idempotencyTtlMs = 24 * 60 * 60 * 1000;

  /**
   * Register a tool with manifest and handler
   */
  register<I, O>(registration: Omit<ToolRegistration<I, O>, "registeredAt">): void {
    // Validate manifest
    const validation = this.validateManifest(registration.manifest);
    if (!validation.valid) {
      throw new Error(`Invalid tool manifest: ${validation.errors?.join(", ")}`);
    }

    // Store by id and version
    if (!this.tools.has(registration.manifest.id)) {
      this.tools.set(registration.manifest.id, new Map());
    }

    const versions = this.tools.get(registration.manifest.id) ?? new Map();
    this.tools.set(registration.manifest.id, versions);
    versions.set(registration.manifest.version, {
      ...registration,
      handler: (input: unknown, context: ToolContext) => registration.handler(input as I, context),
      registeredAt: new Date().toISOString(),
    });
  }

  /**
   * Get tool registration
   */
  getRegistration(toolId: string, version?: string): ToolRegistration | undefined {
    const versions = this.tools.get(toolId);
    if (!versions) return undefined;

    if (version) {
      return versions.get(version);
    }

    // Return latest version if not specified
    const sorted = Array.from(versions.values()).sort((a, b) =>
      b.registeredAt.localeCompare(a.registeredAt),
    );
    return sorted[0];
  }

  /**
   * Create a tool port for an agent run
   */
  createToolPort(_runId: string, _attemptId: string, _scope: AgentScope): ToolPort {
    return {
      invoke: async <I, O>(invocation: ToolInvocation<I>): Promise<ToolResult<O>> => {
        return this.invoke<I, O>(invocation);
      },

      available: async (toolId: string, version?: string): Promise<boolean> => {
        const registration = this.getRegistration(toolId, version);
        return registration !== undefined;
      },

      getManifest: async (toolId: string, version?: string): Promise<ToolManifest | undefined> => {
        const registration = this.getRegistration(toolId, version);
        return registration?.manifest;
      },
    };
  }

  /**
   * Invoke a tool
   */
  async invoke<I, O>(invocation: ToolInvocation<I>): Promise<ToolResult<O>> {
    const registration = this.getRegistration(invocation.toolId, invocation.version);
    const key = invocation.context.idempotencyKey;
    if (!registration || !key || !registration.manifest.idempotent) {
      return this.invokeInternal(invocation);
    }
    this.pruneIdempotencyCache();
    const cacheKey = idempotencyIdentity(invocation.toolId, key, invocation.context);
    const inputHash = stableJson(invocation.input);
    const cached = this.idempotencyCache.get(cacheKey);
    if (cached) {
      if (cached.inputHash !== inputHash) return idempotencyConflict<ToolResult<O>>();
      return cached.result as ToolResult<O>;
    }
    const pending = this.idempotencyInFlight.get(cacheKey);
    if (pending) {
      if (pending.inputHash !== inputHash) return idempotencyConflict<ToolResult<O>>();
      return (await pending.result) as ToolResult<O>;
    }
    const execution = this.invokeInternal(invocation);
    this.idempotencyInFlight.set(cacheKey, { inputHash, result: execution });
    try {
      const result = await execution;
      if (result.status === "success") {
        this.idempotencyCache.set(cacheKey, {
          inputHash,
          result,
          expiresAt: Date.now() + this.idempotencyTtlMs,
        });
        this.pruneIdempotencyCache();
      }
      return result as ToolResult<O>;
    } finally {
      this.idempotencyInFlight.delete(cacheKey);
    }
  }

  private async invokeInternal<I, O>(invocation: ToolInvocation<I>): Promise<ToolResult<O>> {
    const { toolId, version, input, context } = invocation;

    // Get tool registration
    const registration = this.getRegistration(toolId, version);
    if (!registration) {
      return {
        status: "error",
        error: {
          code: "tool_not_found",
          message: `Tool ${toolId}${version ? `@${version}` : ""} not found`,
          class: "permanent",
          retryable: false,
          safeMessage: "Tool not found",
        },
      };
    }

    // Validate input size
    const inputJson = JSON.stringify(input);
    const inputBytes = Buffer.byteLength(inputJson, "utf8");
    if (inputBytes > registration.manifest.limits.maxInputBytes) {
      return {
        status: "error",
        error: {
          code: "input_too_large",
          message: `Input size ${inputBytes} exceeds limit ${registration.manifest.limits.maxInputBytes}`,
          class: "validation",
          retryable: false,
          safeMessage: "Input too large",
        },
      };
    }

    // Check deadline
    const now = Date.now();
    if (context.deadline && now > context.deadline) {
      return {
        status: "timeout",
        error: {
          code: "deadline_exceeded",
          message: "Deadline exceeded before invocation",
          class: "transient",
          retryable: true,
          safeMessage: "Request timed out",
        },
      };
    }

    // Create execution record
    const executionId = `exec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const execution: ToolExecution = {
      id: executionId,
      toolId,
      version: registration.manifest.version,
      runId: context.runId,
      attemptId: context.attemptId,
      scope: context.scope,
      idempotencyKey: context.idempotencyKey,
      startedAt: new Date().toISOString(),
      status: "running",
      input,
    };

    if (!this.executions.has(context.runId)) {
      this.executions.set(context.runId, []);
    }
    this.executions.get(context.runId)?.push(execution);

    // Execute with timeout
    const startTime = Date.now();
    const timeoutMs = Math.min(
      registration.manifest.limits.timeoutMs,
      context.deadline ? context.deadline - now : registration.manifest.limits.timeoutMs,
    );

    try {
      const result = await Promise.race([
        registration.handler(input, context),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("Timeout")), timeoutMs),
        ),
      ]);

      const durationMs = Date.now() - startTime;

      // Validate output size
      const outputJson = JSON.stringify(result);
      const outputBytes = Buffer.byteLength(outputJson, "utf8");
      if (outputBytes > registration.manifest.limits.maxOutputBytes) {
        execution.status = "error";
        execution.completedAt = new Date().toISOString();
        execution.durationMs = durationMs;

        const errorResult: ToolResult<O> = {
          status: "error",
          error: {
            code: "output_too_large",
            message: `Output size ${outputBytes} exceeds limit ${registration.manifest.limits.maxOutputBytes}`,
            class: "permanent",
            retryable: false,
            safeMessage: "Output too large",
          },
        };

        return errorResult;
      }

      // Validate output schema if specified
      if (registration.manifest.outputSchema) {
        const schemaValidation = this.validateOutputSchema(
          result,
          registration.manifest.outputSchema,
        );
        if (!schemaValidation.valid) {
          execution.status = "error";
          execution.completedAt = new Date().toISOString();
          execution.durationMs = durationMs;

          const errorResult: ToolResult<O> = {
            status: "error",
            error: {
              code: "invalid_output",
              message: `Output validation failed: ${schemaValidation.errors?.join(", ")}`,
              class: "permanent",
              retryable: false,
              safeMessage: "Invalid output",
            },
          };

          return errorResult;
        }
      }

      // Success
      execution.status = "success";
      execution.output = result;
      execution.completedAt = new Date().toISOString();
      execution.durationMs = durationMs;

      const successResult: ToolResult<O> = {
        status: "success",
        output: result as O,
        usage: {
          durationMs,
        },
        evidence: [
          {
            type: "receipt",
            id: executionId,
            timestamp: execution.completedAt,
            verified: true,
          },
        ],
      };

      return successResult;
    } catch (error) {
      const durationMs = Date.now() - startTime;
      execution.completedAt = new Date().toISOString();
      execution.durationMs = durationMs;

      const errorMessage = error instanceof Error ? error.message : String(error);
      const isTimeout = errorMessage.includes("Timeout") || errorMessage.includes("timeout");

      execution.status = isTimeout ? "timeout" : "error";

      const toolError: ToolError = {
        code: isTimeout ? "timeout" : "execution_error",
        message: errorMessage,
        class: isTimeout ? "transient" : "unknown",
        retryable: isTimeout,
        safeMessage: isTimeout ? "Request timed out" : "Tool execution failed",
      };

      execution.error = toolError;

      return {
        status: execution.status as "timeout" | "error",
        error: toolError,
        usage: {
          durationMs,
        },
      };
    }
  }

  private pruneIdempotencyCache(): void {
    const now = Date.now();
    for (const [key, value] of this.idempotencyCache) {
      if (value.expiresAt <= now) this.idempotencyCache.delete(key);
    }
    while (this.idempotencyCache.size >= this.maxIdempotencyEntries) {
      const oldest = this.idempotencyCache.keys().next().value;
      if (oldest === undefined) break;
      this.idempotencyCache.delete(oldest);
    }
  }

  /**
   * Get executions for a run
   */
  getRunExecutions(runId: string): ToolExecution[] {
    return this.executions.get(runId) || [];
  }

  /**
   * Get execution statistics
   */
  getStatistics(options?: { toolId?: string; runId?: string }): {
    totalExecutions: number;
    successCount: number;
    errorCount: number;
    timeoutCount: number;
    averageDurationMs: number;
  } {
    let executions: ToolExecution[] = [];

    if (options?.runId) {
      executions = this.getRunExecutions(options.runId);
    } else {
      for (const runExecs of this.executions.values()) {
        executions.push(...runExecs);
      }
    }

    if (options?.toolId) {
      executions = executions.filter((e) => e.toolId === options.toolId);
    }

    if (executions.length === 0) {
      return {
        totalExecutions: 0,
        successCount: 0,
        errorCount: 0,
        timeoutCount: 0,
        averageDurationMs: 0,
      };
    }

    const successCount = executions.filter((e) => e.status === "success").length;
    const errorCount = executions.filter((e) => e.status === "error").length;
    const timeoutCount = executions.filter((e) => e.status === "timeout").length;

    const totalDuration = executions.reduce((sum, e) => sum + (e.durationMs || 0), 0);
    const averageDurationMs = totalDuration / executions.length;

    return {
      totalExecutions: executions.length,
      successCount,
      errorCount,
      timeoutCount,
      averageDurationMs,
    };
  }

  /**
   * Validate tool manifest
   */
  private validateManifest(manifest: ToolManifest): { valid: boolean; errors?: string[] } {
    const errors: string[] = [];

    if (!manifest.id) errors.push("id is required");
    if (!manifest.version) errors.push("version is required");
    if (!manifest.displayName) errors.push("displayName is required");
    if (!manifest.inputSchema) errors.push("inputSchema is required");
    if (!manifest.effectClass) errors.push("effectClass is required");
    if (manifest.idempotent === undefined) errors.push("idempotent is required");
    if (!manifest.limits) errors.push("limits is required");
    if (!manifest.sensitivity) errors.push("sensitivity is required");

    if (manifest.limits) {
      if (manifest.limits.maxInputBytes <= 0) errors.push("maxInputBytes must be positive");
      if (manifest.limits.maxOutputBytes <= 0) errors.push("maxOutputBytes must be positive");
      if (manifest.limits.timeoutMs <= 0) errors.push("timeoutMs must be positive");
    }

    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  /**
   * Validate output against schema
   */
  private validateOutputSchema(
    output: unknown,
    schema: Record<string, unknown>,
  ): { valid: boolean; errors?: string[] } {
    const errors: string[] = [];

    if (schema.type === "object" && typeof output !== "object") {
      errors.push("Output must be an object");
      return { valid: false, errors };
    }

    if (schema.type === "array" && !Array.isArray(output)) {
      errors.push("Output must be an array");
      return { valid: false, errors };
    }

    if (schema.type === "object" && typeof output === "object" && output !== null) {
      const required = (schema.required as string[]) || [];
      for (const field of required) {
        if (!(field in output)) {
          errors.push(`Missing required field: ${field}`);
        }
      }

      // Check if schema has properties definition
      const properties = schema.properties as Record<string, unknown> | undefined;
      if (properties) {
        // Check if output has unexpected properties
        const outputKeys = Object.keys(output);
        const schemaKeys = Object.keys(properties);

        for (const key of outputKeys) {
          if (!schemaKeys.includes(key)) {
            errors.push(`Unexpected field: ${key}`);
          }
        }

        // Check if all required properties exist
        for (const key of schemaKeys) {
          if (!(key in output)) {
            // Only error if not already caught by required check
            if (!required.includes(key)) {
              errors.push(`Missing field: ${key}`);
            }
          }
        }
      }
    }

    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  /**
   * List all tools
   */
  listTools(): Array<{ id: string; versions: string[] }> {
    return Array.from(this.tools.entries()).map(([id, versions]) => ({
      id,
      versions: Array.from(versions.keys()),
    }));
  }
}
