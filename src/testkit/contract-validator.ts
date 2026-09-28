/**
 * Contract Validation Test Kit
 * Utilities for validating agent contracts against schemas
 */

import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import {
  AgentManifest,
  AgentManifestSchema,
  AgentResult,
  AgentResultWireSchema,
  JsonValue,
  StructuredError,
  StructuredErrorSchema,
} from "../contracts/index.js";

// Load schemas

export class ContractValidator {
  private ajv: Ajv2020;
  private validators: Map<string, ValidateFunction>;

  constructor() {
    this.ajv = new Ajv2020({
      allErrors: true,
      strict: true,
      validateFormats: true,
    });
    this.ajv.addFormat("date-time", fullFormats["date-time"]);

    this.validators = new Map();
    this.registerSchemas();
  }

  private registerSchemas(): void {
    // Register all schemas
    this.ajv.addSchema(AgentManifestSchema, "agent-manifest");
    this.ajv.addSchema(AgentResultWireSchema, "agent-result");
    this.ajv.addSchema(StructuredErrorSchema, "structured-error");

    // Compile validators
    for (const schemaId of ["agent-manifest", "agent-result", "structured-error"]) {
      const validator = this.ajv.getSchema(schemaId);
      if (!validator) throw new Error(`Failed to compile schema: ${schemaId}`);
      this.validators.set(schemaId, validator);
    }
  }

  /**
   * Validate an agent manifest
   */
  validateManifest(manifest: unknown): ValidationResult<AgentManifest> {
    return this.validate<AgentManifest>("agent-manifest", manifest);
  }

  /**
   * Validate an agent result
   */
  validateResult<O extends JsonValue = JsonValue>(
    result: unknown,
  ): ValidationResult<AgentResult<O>> {
    return this.validate<AgentResult<O>>("agent-result", result);
  }

  /**
   * Validate a structured error
   */
  validateError(error: unknown): ValidationResult<StructuredError> {
    return this.validate<StructuredError>("structured-error", error);
  }

  /**
   * Generic validation method
   */
  private validate<T>(schemaId: string, data: unknown): ValidationResult<T> {
    const validator = this.validators.get(schemaId);
    if (!validator) {
      return {
        valid: false,
        errors: [`Unknown schema: ${schemaId}`],
      };
    }

    const valid = validator(data);
    if (valid) {
      return {
        valid: true,
        data: data as T,
      };
    }

    const errors = validator.errors?.map((err) => `${err.instancePath} ${err.message}`) || [
      "Unknown validation error",
    ];

    return {
      valid: false,
      errors,
    };
  }
}

export interface ValidationResult<T> {
  valid: boolean;
  data?: T;
  errors?: string[];
}

/**
 * Create a validation result for successful validation
 */
export function validResult<T>(data: T): ValidationResult<T> {
  return { valid: true, data };
}

/**
 * Create a validation result for failed validation
 */
export function invalidResult<T>(errors: string[]): ValidationResult<T> {
  return { valid: false, errors };
}

/**
 * Assert that a value is valid according to a validator
 */
export function assertValid<T>(
  result: ValidationResult<T>,
  message?: string,
): asserts result is ValidationResult<T> & { valid: true; data: T } {
  if (!result.valid) {
    const errorMsg = message || "Validation failed";
    const errors = result.errors?.join(", ") || "unknown errors";
    throw new Error(`${errorMsg}: ${errors}`);
  }
}

/**
 * Test utilities for contract validation
 */
export class ContractTestKit {
  private validator: ContractValidator;

  constructor() {
    this.validator = new ContractValidator();
  }

  /**
   * Create a minimal valid agent manifest for testing
   */
  createMinimalManifest(overrides?: Partial<AgentManifest>): AgentManifest {
    return {
      apiVersion: "agent.v1",
      id: "test-agent",
      version: "1.0.0",
      displayName: "Test Agent",
      inputSchema: { type: "object" },
      outputSchema: { type: "object" },
      capabilities: [],
      requiredPorts: [],
      toolGrants: [],
      limits: {
        timeoutMs: 60000,
        maxInputBytes: 1048576,
        maxOutputBytes: 1048576,
        maxEventBytes: 1048576,
        maxCheckpointBytes: 1048576,
        maxModelCalls: 100,
        maxToolCalls: 100,
        maxChildRuns: 10,
        maxDepth: 5,
        maxCostUsd: 10,
      },
      compatibility: {
        minHostVersion: "1.0.0",
      },
      ...overrides,
    };
  }

  /**
   * Create a minimal valid agent result for testing
   */
  createMinimalResult<O extends JsonValue = JsonValue>(
    overrides?: Partial<AgentResult<O>>,
  ): AgentResult<O> {
    const baseResult = {
      status: "completed" as const,
      output: {} as O,
      artifacts: [],
      evidence: [],
      usage: {
        inputTokens: 100,
        outputTokens: 50,
        cacheReadTokens: 0,
        cacheWriteTokens: 0,
        modelCalls: 1,
        toolCalls: 0,
        durationMs: 1000,
        estimatedCostUsd: 0.001,
      },
      warnings: [],
    };

    return { ...baseResult, ...overrides } as AgentResult<O>;
  }

  /**
   * Create a minimal valid structured error for testing
   */
  createMinimalError(overrides?: Partial<StructuredError>): StructuredError {
    return {
      code: "TEST_ERROR",
      class: "transient",
      retryable: true,
      safeMessage: "Test error message",
      correlationId: "test-correlation-123",
      ...overrides,
    };
  }

  /**
   * Validate and assert a manifest is valid
   */
  expectValidManifest(manifest: unknown): AgentManifest {
    const result = this.validator.validateManifest(manifest);
    assertValid(result, "Expected valid manifest");
    return result.data;
  }

  /**
   * Validate and expect a manifest to be invalid
   */
  expectInvalidManifest(manifest: unknown): string[] {
    const result = this.validator.validateManifest(manifest);
    if (result.valid) {
      throw new Error("Expected manifest to be invalid, but it was valid");
    }
    return result.errors || [];
  }

  /**
   * Validate and assert a result is valid
   */
  expectValidResult<O extends JsonValue = JsonValue>(result: unknown): AgentResult<O> {
    const validationResult = this.validator.validateResult<O>(result);
    assertValid(validationResult, "Expected valid result");
    return validationResult.data;
  }

  /**
   * Validate and expect a result to be invalid
   */
  expectInvalidResult(result: unknown): string[] {
    const validationResult = this.validator.validateResult(result);
    if (validationResult.valid) {
      throw new Error("Expected result to be invalid, but it was valid");
    }
    return validationResult.errors || [];
  }
}

/**
 * Global validator instance
 */
export const contractValidator = new ContractValidator();

/**
 * Global test kit instance
 */
export const contractTestKit = new ContractTestKit();
