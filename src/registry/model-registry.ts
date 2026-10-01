/**
 * Model Registry
 * Manages model profiles, provider adapters, and usage tracking
 */

/** Prototype provider gateway; it is not the public ModelPort wire contract. */
export interface RegistryModelPort {
  complete(
    request: Omit<Parameters<ModelProvider["complete"]>[0], "deadline"> & { deadline?: number },
  ): ReturnType<ModelProvider["complete"]>;
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: string;
  contextWindow: number;
  maxOutputTokens: number;
  supportsFunctions: boolean;
  supportsVision: boolean;
  costPer1kInput: number;
  costPer1kOutput: number;
  costPer1kCacheWrite?: number;
  costPer1kCacheRead?: number;
}

export interface ModelUsage {
  runId: string;
  attemptId: string;
  modelId: string;
  provider: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  estimatedCost: number;
  timestamp: string;
  deadline: number;
  actualDuration: number;
}

export interface ModelProvider {
  name: string;
  complete(params: {
    model: string;
    messages: Array<{ role: string; content: string }>;
    temperature?: number;
    maxTokens?: number;
    schema?: unknown;
    deadline: number;
  }): Promise<{
    content: string;
    usage: {
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens?: number;
      cacheWriteTokens?: number;
    };
    finishReason: string;
    requestId: string;
  }>;
}

export class ModelRegistry {
  private profiles = new Map<string, ModelProfile>();
  private providers = new Map<string, ModelProvider>();
  private usageLedger: ModelUsage[] = [];

  /**
   * Register a model profile
   */
  registerProfile(profile: ModelProfile): void {
    this.profiles.set(profile.id, profile);
  }

  /**
   * Register a provider adapter
   */
  registerProvider(provider: ModelProvider): void {
    this.providers.set(provider.name, provider);
  }

  /**
   * Get model profile
   */
  getProfile(modelId: string): ModelProfile | undefined {
    return this.profiles.get(modelId);
  }

  /**
   * List all available models
   */
  listProfiles(): ModelProfile[] {
    return Array.from(this.profiles.values());
  }

  /**
   * List models by provider
   */
  listByProvider(provider: string): ModelProfile[] {
    return Array.from(this.profiles.values()).filter((p) => p.provider === provider);
  }

  /**
   * Create model port with usage tracking
   */
  createModelPort(runId: string, attemptId: string): RegistryModelPort {
    return {
      complete: async (request) => {
        const profile = this.getProfile(request.model || "claude-3-5-sonnet-20241022");
        if (!profile) {
          throw new Error(`Model profile not found: ${request.model}`);
        }

        const provider = this.providers.get(profile.provider);
        if (!provider) {
          throw new Error(`Provider not found: ${profile.provider}`);
        }

        // Execute request
        const startTime = Date.now();
        const result = await provider.complete({
          ...request,
          model: profile.id,
          deadline: request.deadline || Date.now() + 60000,
        });

        // Calculate cost
        const cost = this.calculateCost(profile, result.usage);

        // Record usage
        this.recordUsage({
          runId,
          attemptId,
          modelId: profile.id,
          provider: profile.provider,
          inputTokens: result.usage.inputTokens,
          outputTokens: result.usage.outputTokens,
          cacheReadTokens: result.usage.cacheReadTokens || 0,
          cacheWriteTokens: result.usage.cacheWriteTokens || 0,
          estimatedCost: cost,
          timestamp: new Date().toISOString(),
          deadline: request.deadline || Date.now() + 60000,
          actualDuration: Date.now() - startTime,
        });

        return {
          content: result.content,
          usage: {
            inputTokens: result.usage.inputTokens,
            outputTokens: result.usage.outputTokens,
            cacheReadTokens: result.usage.cacheReadTokens,
            cacheWriteTokens: result.usage.cacheWriteTokens,
          },
          finishReason: result.finishReason,
          requestId: result.requestId,
        };
      },
    };
  }

  /**
   * Calculate cost for model usage
   */
  private calculateCost(
    profile: ModelProfile,
    usage: {
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens?: number;
      cacheWriteTokens?: number;
    },
  ): number {
    let cost = 0;

    // Input tokens
    cost += (usage.inputTokens / 1000) * profile.costPer1kInput;

    // Output tokens
    cost += (usage.outputTokens / 1000) * profile.costPer1kOutput;

    // Cache read tokens
    if (usage.cacheReadTokens && profile.costPer1kCacheRead) {
      cost += (usage.cacheReadTokens / 1000) * profile.costPer1kCacheRead;
    }

    // Cache write tokens
    if (usage.cacheWriteTokens && profile.costPer1kCacheWrite) {
      cost += (usage.cacheWriteTokens / 1000) * profile.costPer1kCacheWrite;
    }

    return cost;
  }

  /**
   * Record usage in ledger
   */
  private recordUsage(usage: ModelUsage): void {
    this.usageLedger.push(usage);
  }

  /**
   * Get usage for a run
   */
  getRunUsage(runId: string): ModelUsage[] {
    return this.usageLedger.filter((u) => u.runId === runId);
  }

  /**
   * Get total cost for a run
   */
  getRunCost(runId: string): number {
    return this.getRunUsage(runId).reduce((sum, u) => sum + u.estimatedCost, 0);
  }

  /**
   * Validate schema output
   */
  validateSchemaOutput(output: unknown, schema: unknown): { valid: boolean; errors?: string[] } {
    // Simple schema validation - in production would use ajv or similar
    if (schema === undefined || schema === null) return { valid: true };
    if (typeof schema === "boolean") {
      return schema ? { valid: true } : { valid: false, errors: ["Output rejected by schema"] };
    }
    if (typeof schema !== "object" || Array.isArray(schema)) {
      return { valid: false, errors: ["Schema must be an object"] };
    }
    const schemaRecord = schema as Record<string, unknown>;

    const errors: string[] = [];

    if (schemaRecord.type === "object" && (typeof output !== "object" || output === null)) {
      errors.push("Output must be an object");
    }

    if (schemaRecord.type === "array" && !Array.isArray(output)) {
      errors.push("Output must be an array");
    }

    if (Array.isArray(schemaRecord.required) && typeof output === "object" && output !== null) {
      for (const field of schemaRecord.required) {
        if (typeof field !== "string") continue;
        if (!(field in output)) {
          errors.push(`Missing required field: ${field}`);
        }
      }
    }

    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  /**
   * Check if run is within deadline
   */
  checkDeadline(deadline: number): boolean {
    return Date.now() < deadline;
  }

  /**
   * Get usage statistics
   */
  getStatistics(options?: { provider?: string; modelId?: string; since?: string }): {
    totalCalls: number;
    totalInputTokens: number;
    totalOutputTokens: number;
    totalCost: number;
    averageDuration: number;
  } {
    let filtered = this.usageLedger;

    if (options?.provider) {
      filtered = filtered.filter((u) => u.provider === options.provider);
    }

    if (options?.modelId) {
      filtered = filtered.filter((u) => u.modelId === options.modelId);
    }

    if (options?.since) {
      const since = options.since;
      filtered = filtered.filter((u) => u.timestamp >= since);
    }

    if (filtered.length === 0) {
      return {
        totalCalls: 0,
        totalInputTokens: 0,
        totalOutputTokens: 0,
        totalCost: 0,
        averageDuration: 0,
      };
    }

    return {
      totalCalls: filtered.length,
      totalInputTokens: filtered.reduce((sum, u) => sum + u.inputTokens, 0),
      totalOutputTokens: filtered.reduce((sum, u) => sum + u.outputTokens, 0),
      totalCost: filtered.reduce((sum, u) => sum + u.estimatedCost, 0),
      averageDuration: filtered.reduce((sum, u) => sum + u.actualDuration, 0) / filtered.length,
    };
  }
}

/**
 * Default model profiles
 */
export const defaultProfiles: ModelProfile[] = [
  {
    id: "claude-3-5-sonnet-20241022",
    name: "Claude 3.5 Sonnet",
    provider: "anthropic",
    contextWindow: 200000,
    maxOutputTokens: 8192,
    supportsFunctions: true,
    supportsVision: true,
    costPer1kInput: 0.003,
    costPer1kOutput: 0.015,
    costPer1kCacheWrite: 0.00375,
    costPer1kCacheRead: 0.0003,
  },
  {
    id: "claude-3-5-haiku-20241022",
    name: "Claude 3.5 Haiku",
    provider: "anthropic",
    contextWindow: 200000,
    maxOutputTokens: 8192,
    supportsFunctions: true,
    supportsVision: true,
    costPer1kInput: 0.001,
    costPer1kOutput: 0.005,
    costPer1kCacheWrite: 0.00125,
    costPer1kCacheRead: 0.0001,
  },
  {
    id: "claude-3-opus-20240229",
    name: "Claude 3 Opus",
    provider: "anthropic",
    contextWindow: 200000,
    maxOutputTokens: 4096,
    supportsFunctions: true,
    supportsVision: true,
    costPer1kInput: 0.015,
    costPer1kOutput: 0.075,
    costPer1kCacheWrite: 0.01875,
    costPer1kCacheRead: 0.0015,
  },
];
