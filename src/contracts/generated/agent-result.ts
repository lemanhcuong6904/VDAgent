// Generated from schemas/agent-result.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.
type AgentResultWireArtifact =
  | {
      id: string;
      workspaceId: string;
      ownerRunId: string;
      kind: string;
      version: string;
      status: "ready";
      sha256: string;
      bytes: number;
    }
  | {
      id: string;
      workspaceId: string;
      ownerRunId: string;
      kind: string;
      version: string;
      status: "pending";
    }
  | {
      id: string;
      workspaceId: string;
      ownerRunId: string;
      kind: string;
      version: string;
      status: "unknown";
    };
type AgentResultWireEvidence = {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  fence: string;
  policyRevision: string;
  kind: "claim" | "process_exit" | "observer_hint" | "receipt";
  verification: "unverified" | "verified" | "unavailable";
};
type AgentResultWireUsage = {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  modelCalls: number;
  toolCalls: number;
  durationMs: number;
  estimatedCostUsd: number;
};
type AgentResultWireWait =
  | {
      reason: "input";
      idempotencyKey: string;
      expiresAt: string;
      requestId: string;
      safeMessage: string;
    }
  | {
      reason: "approval";
      idempotencyKey: string;
      expiresAt: string;
      requestId: string;
      safeMessage: string;
      actionId: string;
    }
  | { reason: "children"; idempotencyKey: string; expiresAt: string; runIds: Array<string> }
  | { reason: "tool"; idempotencyKey: string; expiresAt: string; executionId: string }
  | { reason: "peer"; idempotencyKey: string; expiresAt: string; messageId: string };
type AgentResultWireJson =
  | null
  | boolean
  | number
  | string
  | Array<AgentResultWireJson>
  | { [key: string]: AgentResultWireJson };
export type AgentResultWire =
  | {
      artifacts: Array<AgentResultWireArtifact>;
      evidence: Array<AgentResultWireEvidence>;
      usage: AgentResultWireUsage;
      warnings: Array<string>;
      status: "completed";
      output: AgentResultWireJson;
    }
  | {
      artifacts: Array<AgentResultWireArtifact>;
      evidence: Array<AgentResultWireEvidence>;
      usage: AgentResultWireUsage;
      warnings: Array<string>;
      status: "waiting";
      wait: AgentResultWireWait;
    }
  | {
      artifacts: Array<AgentResultWireArtifact>;
      evidence: Array<AgentResultWireEvidence>;
      usage: AgentResultWireUsage;
      warnings: Array<string>;
      status: "needs_approval";
      wait: {
        reason: "approval";
        idempotencyKey: string;
        expiresAt: string;
        requestId: string;
        safeMessage: string;
        actionId: string;
      };
    }
  | {
      artifacts: Array<AgentResultWireArtifact>;
      evidence: Array<AgentResultWireEvidence>;
      usage: AgentResultWireUsage;
      warnings: Array<string>;
      status: "needs_input";
      wait: {
        reason: "input";
        idempotencyKey: string;
        expiresAt: string;
        requestId: string;
        safeMessage: string;
      };
    };
export const AgentResultWireSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:agent-result:v1",
  title: "AgentResultWire",
  $defs: {
    Artifact: {
      oneOf: [
        {
          type: "object",
          additionalProperties: false,
          properties: {
            id: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            workspaceId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            ownerRunId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            kind: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            version: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            status: {
              type: "string",
              const: "ready",
              maxLength: 16,
            },
            sha256: {
              type: "string",
              minLength: 1,
              maxLength: 64,
              pattern: "^[a-f0-9]{64}$",
            },
            bytes: {
              type: "integer",
              minimum: 0,
              maximum: 9007199254740991,
            },
          },
          required: [
            "id",
            "workspaceId",
            "ownerRunId",
            "kind",
            "version",
            "status",
            "sha256",
            "bytes",
          ],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            id: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            workspaceId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            ownerRunId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            kind: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            version: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            status: {
              type: "string",
              const: "pending",
              maxLength: 16,
            },
          },
          required: ["id", "workspaceId", "ownerRunId", "kind", "version", "status"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            id: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            workspaceId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            ownerRunId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            kind: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            version: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            status: {
              type: "string",
              const: "unknown",
              maxLength: 16,
            },
          },
          required: ["id", "workspaceId", "ownerRunId", "kind", "version", "status"],
        },
      ],
    },
    Evidence: {
      type: "object",
      additionalProperties: false,
      properties: {
        id: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        workspaceId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        runId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        attemptId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        fence: {
          type: "string",
          minLength: 1,
          maxLength: 32,
          pattern: "^[1-9][0-9]*$",
        },
        policyRevision: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        kind: {
          type: "string",
          enum: ["claim", "process_exit", "observer_hint", "receipt"],
        },
        verification: {
          type: "string",
          enum: ["unverified", "verified", "unavailable"],
        },
      },
      required: [
        "id",
        "workspaceId",
        "runId",
        "attemptId",
        "fence",
        "policyRevision",
        "kind",
        "verification",
      ],
    },
    Usage: {
      type: "object",
      additionalProperties: false,
      properties: {
        inputTokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        outputTokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        cacheReadTokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        cacheWriteTokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        modelCalls: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        toolCalls: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        durationMs: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        estimatedCostUsd: {
          type: "number",
          minimum: 0,
          maximum: 1000000000,
        },
      },
      required: [
        "inputTokens",
        "outputTokens",
        "cacheReadTokens",
        "cacheWriteTokens",
        "modelCalls",
        "toolCalls",
        "durationMs",
        "estimatedCostUsd",
      ],
    },
    Wait: {
      oneOf: [
        {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "input",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            requestId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            safeMessage: {
              type: "string",
              minLength: 1,
              maxLength: 2048,
            },
          },
          required: ["reason", "idempotencyKey", "expiresAt", "requestId", "safeMessage"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "approval",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            requestId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            safeMessage: {
              type: "string",
              minLength: 1,
              maxLength: 2048,
            },
            actionId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
          },
          required: [
            "reason",
            "idempotencyKey",
            "expiresAt",
            "requestId",
            "safeMessage",
            "actionId",
          ],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "children",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            runIds: {
              type: "array",
              minItems: 1,
              maxItems: 64,
              items: {
                type: "string",
                minLength: 1,
                maxLength: 128,
                pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
              },
            },
          },
          required: ["reason", "idempotencyKey", "expiresAt", "runIds"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "tool",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            executionId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
          },
          required: ["reason", "idempotencyKey", "expiresAt", "executionId"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "peer",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            messageId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
          },
          required: ["reason", "idempotencyKey", "expiresAt", "messageId"],
        },
      ],
    },
    Json: {
      anyOf: [
        {
          type: "null",
        },
        {
          type: "boolean",
        },
        {
          type: "number",
          minimum: -1.7976931348623157e308,
          maximum: 1.7976931348623157e308,
        },
        {
          type: "string",
          maxLength: 1048576,
        },
        {
          type: "array",
          maxItems: 10000,
          items: {
            $ref: "#/$defs/Json",
          },
        },
        {
          type: "object",
          maxProperties: 10000,
          propertyNames: {
            type: "string",
            maxLength: 256,
          },
          additionalProperties: {
            $ref: "#/$defs/Json",
          },
        },
      ],
    },
  },
  oneOf: [
    {
      type: "object",
      additionalProperties: false,
      properties: {
        artifacts: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Artifact",
          },
        },
        evidence: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Evidence",
          },
        },
        usage: {
          $ref: "#/$defs/Usage",
        },
        warnings: {
          type: "array",
          maxItems: 64,
          items: {
            type: "string",
            maxLength: 2048,
          },
        },
        status: {
          type: "string",
          const: "completed",
          maxLength: 32,
        },
        output: {
          $ref: "#/$defs/Json",
        },
      },
      required: ["artifacts", "evidence", "usage", "warnings", "status", "output"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        artifacts: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Artifact",
          },
        },
        evidence: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Evidence",
          },
        },
        usage: {
          $ref: "#/$defs/Usage",
        },
        warnings: {
          type: "array",
          maxItems: 64,
          items: {
            type: "string",
            maxLength: 2048,
          },
        },
        status: {
          type: "string",
          const: "waiting",
          maxLength: 32,
        },
        wait: {
          $ref: "#/$defs/Wait",
        },
      },
      required: ["artifacts", "evidence", "usage", "warnings", "status", "wait"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        artifacts: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Artifact",
          },
        },
        evidence: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Evidence",
          },
        },
        usage: {
          $ref: "#/$defs/Usage",
        },
        warnings: {
          type: "array",
          maxItems: 64,
          items: {
            type: "string",
            maxLength: 2048,
          },
        },
        status: {
          type: "string",
          const: "needs_approval",
          maxLength: 32,
        },
        wait: {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "approval",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            requestId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            safeMessage: {
              type: "string",
              minLength: 1,
              maxLength: 2048,
            },
            actionId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
          },
          required: [
            "reason",
            "idempotencyKey",
            "expiresAt",
            "requestId",
            "safeMessage",
            "actionId",
          ],
        },
      },
      required: ["artifacts", "evidence", "usage", "warnings", "status", "wait"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        artifacts: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Artifact",
          },
        },
        evidence: {
          type: "array",
          maxItems: 128,
          items: {
            $ref: "#/$defs/Evidence",
          },
        },
        usage: {
          $ref: "#/$defs/Usage",
        },
        warnings: {
          type: "array",
          maxItems: 64,
          items: {
            type: "string",
            maxLength: 2048,
          },
        },
        status: {
          type: "string",
          const: "needs_input",
          maxLength: 32,
        },
        wait: {
          type: "object",
          additionalProperties: false,
          properties: {
            reason: {
              type: "string",
              const: "input",
              maxLength: 16,
            },
            idempotencyKey: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            expiresAt: {
              type: "string",
              minLength: 1,
              maxLength: 32,
              format: "date-time",
              pattern: "Z$",
            },
            requestId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            safeMessage: {
              type: "string",
              minLength: 1,
              maxLength: 2048,
            },
          },
          required: ["reason", "idempotencyKey", "expiresAt", "requestId", "safeMessage"],
        },
      },
      required: ["artifacts", "evidence", "usage", "warnings", "status", "wait"],
    },
  ],
} as const;
