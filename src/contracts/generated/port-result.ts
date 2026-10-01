// Generated from schemas/port-result.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.
type PortResultWireJson =
  | null
  | boolean
  | number
  | string
  | Array<PortResultWireJson>
  | { [key: string]: PortResultWireJson };
type PortResultWireEvidence = {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  fence: string;
  policyRevision: string;
  kind: "claim" | "process_exit" | "observer_hint" | "receipt";
  verification: "unverified" | "verified" | "unavailable";
};
type PortResultWireArtifact =
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
type PortResultWireUsage = {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  modelCalls: number;
  toolCalls: number;
  durationMs: number;
  estimatedCostUsd: number;
};
type PortResultWireError = {
  code: string;
  class: "validation" | "policy" | "transient" | "permanent" | "unknown";
  retryable: boolean;
  safeMessage: string;
  correlationId: string;
};
type PortResultWireReadyArtifact = {
  id: string;
  workspaceId: string;
  ownerRunId: string;
  kind: string;
  version: string;
  status: "ready";
  sha256: string;
  bytes: number;
};
type PortResultWirePendingArtifact = {
  id: string;
  workspaceId: string;
  ownerRunId: string;
  kind: string;
  version: string;
  status: "pending";
};
type PortResultWireUnknownError = {
  code: string;
  class: "unknown";
  retryable: false;
  safeMessage: string;
  correlationId: string;
};
type PortResultWireMemoryItem = {
  id: string;
  revision: string;
  content: PortResultWireJson;
  trust: "untrusted";
  scope: "user" | "agent" | "workspace";
  audience: string;
  sensitivity: "public" | "internal" | "private";
  expiresAt: string | null;
  provenance: Array<PortResultWireEvidence>;
};
type PortResultWireNonSuccess =
  | { status: "queued"; operationId: string; evidence: Array<PortResultWireEvidence> }
  | { status: "needs_approval" | "needs_input"; requestId: string; safeMessage: string }
  | {
      status: "denied" | "failed";
      error: PortResultWireError;
      evidence: Array<PortResultWireEvidence>;
    }
  | {
      status: "unknown";
      error: PortResultWireUnknownError;
      evidence: Array<PortResultWireEvidence>;
    };
export type PortResultWire =
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "model.complete";
      outcome:
        | {
            status: "ok";
            output: {
              output: PortResultWireJson;
              usage: PortResultWireUsage;
              finishReason: "stop" | "length" | "tool_call" | "refusal";
              providerRequestId: string;
            };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "tools.invoke";
      outcome:
        | {
            status: "ok";
            output: PortResultWireJson;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "warehouse.catalog";
      outcome:
        | {
            status: "ok";
            output: Array<{ id: string; displayName: string }>;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "warehouse.describe";
      outcome:
        | {
            status: "ok";
            output: { columns: Array<{ name: string; type: string }> };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "warehouse.query";
      outcome:
        | {
            status: "ok";
            output: { rows: Array<PortResultWireJson>; truncated: boolean };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "artifacts.begin";
      outcome:
        | {
            status: "ok";
            output: { uploadId: string; artifact: PortResultWirePendingArtifact };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "artifacts.write";
      outcome:
        | {
            status: "ok";
            output: { acceptedBytes: number };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "artifacts.commit";
      outcome:
        | {
            status: "ok";
            output: PortResultWireReadyArtifact;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "artifacts.read";
      outcome:
        | {
            status: "ok";
            output: {
              artifact: PortResultWireReadyArtifact;
              bytesBase64: string;
              nextOffset: number | null;
            };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "memory.read";
      outcome:
        | {
            status: "ok";
            output: PortResultWireMemoryItem | null;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "memory.search";
      outcome:
        | {
            status: "ok";
            output: Array<PortResultWireMemoryItem>;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "memory.remember";
      outcome:
        | {
            status: "ok";
            output: PortResultWireMemoryItem;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "memory.forget";
      outcome:
        | {
            status: "ok";
            output: { revision: string; deleted: true };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "collaboration.discover";
      outcome:
        | {
            status: "ok";
            output: Array<{ agentId: string; version: string; capabilities: Array<string> }>;
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "collaboration.invoke";
      outcome:
        | {
            status: "ok";
            output: { runId: string };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "collaboration.wait";
      outcome:
        | {
            status: "ok";
            output: { completedRunIds: Array<string> };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "collaboration.result";
      outcome:
        | {
            status: "ok";
            output: {
              status: "running" | "waiting" | "completed" | "failed" | "cancelled";
              output?: PortResultWireJson;
              artifacts: Array<PortResultWireArtifact>;
            };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "sandbox.execute";
      outcome:
        | {
            status: "ok";
            output: {
              executionId: string;
              exitCode: number | null;
              artifacts: Array<PortResultWireArtifact>;
            };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "sandbox.pause";
      outcome:
        | {
            status: "ok";
            output: { checkpointId: string };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    }
  | {
      apiVersion: "port-result.v1";
      callId: string;
      method: "sandbox.resume";
      outcome:
        | {
            status: "ok";
            output: { executionId: string };
            evidence: Array<PortResultWireEvidence>;
            limitations: Array<string>;
          }
        | PortResultWireNonSuccess;
    };
export const PortResultWireSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:port-result:v1",
  title: "PortResultWire",
  $defs: {
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
    Error: {
      type: "object",
      additionalProperties: false,
      properties: {
        code: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        class: {
          type: "string",
          enum: ["validation", "policy", "transient", "permanent", "unknown"],
        },
        retryable: {
          type: "boolean",
        },
        safeMessage: {
          type: "string",
          minLength: 1,
          maxLength: 2048,
        },
        correlationId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
      },
      required: ["code", "class", "retryable", "safeMessage", "correlationId"],
    },
    ReadyArtifact: {
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
      required: ["id", "workspaceId", "ownerRunId", "kind", "version", "status", "sha256", "bytes"],
    },
    PendingArtifact: {
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
    UnknownError: {
      type: "object",
      additionalProperties: false,
      properties: {
        code: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        class: {
          type: "string",
          const: "unknown",
          maxLength: 64,
        },
        retryable: {
          type: "boolean",
          const: false,
        },
        safeMessage: {
          type: "string",
          minLength: 1,
          maxLength: 2048,
        },
        correlationId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
      },
      required: ["code", "class", "retryable", "safeMessage", "correlationId"],
    },
    MemoryItem: {
      type: "object",
      additionalProperties: false,
      properties: {
        id: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        revision: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        content: {
          $ref: "#/$defs/Json",
        },
        trust: {
          type: "string",
          const: "untrusted",
          maxLength: 64,
        },
        scope: {
          type: "string",
          enum: ["user", "agent", "workspace"],
        },
        audience: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        sensitivity: {
          type: "string",
          enum: ["public", "internal", "private"],
        },
        expiresAt: {
          anyOf: [
            {
              type: "string",
              format: "date-time",
              maxLength: 64,
            },
            {
              type: "null",
            },
          ],
        },
        provenance: {
          type: "array",
          maxItems: 1024,
          items: {
            $ref: "#/$defs/Evidence",
          },
        },
      },
      required: [
        "id",
        "revision",
        "content",
        "trust",
        "scope",
        "audience",
        "sensitivity",
        "expiresAt",
        "provenance",
      ],
    },
    NonSuccess: {
      oneOf: [
        {
          type: "object",
          additionalProperties: false,
          properties: {
            status: {
              type: "string",
              const: "queued",
              maxLength: 64,
            },
            operationId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            evidence: {
              type: "array",
              maxItems: 1024,
              items: {
                $ref: "#/$defs/Evidence",
              },
            },
          },
          required: ["status", "operationId", "evidence"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            status: {
              type: "string",
              enum: ["needs_approval", "needs_input"],
            },
            requestId: {
              type: "string",
              minLength: 1,
              maxLength: 128,
              pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            safeMessage: {
              type: "string",
              minLength: 0,
              maxLength: 2048,
            },
          },
          required: ["status", "requestId", "safeMessage"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            status: {
              type: "string",
              enum: ["denied", "failed"],
            },
            error: {
              $ref: "#/$defs/Error",
            },
            evidence: {
              type: "array",
              maxItems: 1024,
              items: {
                $ref: "#/$defs/Evidence",
              },
            },
          },
          required: ["status", "error", "evidence"],
        },
        {
          type: "object",
          additionalProperties: false,
          properties: {
            status: {
              type: "string",
              const: "unknown",
              maxLength: 64,
            },
            error: {
              $ref: "#/$defs/UnknownError",
            },
            evidence: {
              type: "array",
              maxItems: 1024,
              items: {
                $ref: "#/$defs/Evidence",
              },
            },
          },
          required: ["status", "error", "evidence"],
        },
      ],
    },
  },
  oneOf: [
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "model.complete",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    output: {
                      $ref: "#/$defs/Json",
                    },
                    usage: {
                      $ref: "#/$defs/Usage",
                    },
                    finishReason: {
                      type: "string",
                      enum: ["stop", "length", "tool_call", "refusal"],
                    },
                    providerRequestId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 256,
                    },
                  },
                  required: ["output", "usage", "finishReason", "providerRequestId"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "tools.invoke",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  $ref: "#/$defs/Json",
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "warehouse.catalog",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      id: {
                        type: "string",
                        minLength: 1,
                        maxLength: 128,
                        pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                      },
                      displayName: {
                        type: "string",
                        minLength: 0,
                        maxLength: 256,
                      },
                    },
                    required: ["id", "displayName"],
                  },
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "warehouse.describe",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    columns: {
                      type: "array",
                      maxItems: 10000,
                      items: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          name: {
                            type: "string",
                            minLength: 1,
                            maxLength: 256,
                          },
                          type: {
                            type: "string",
                            minLength: 1,
                            maxLength: 128,
                          },
                        },
                        required: ["name", "type"],
                      },
                    },
                  },
                  required: ["columns"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "warehouse.query",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    rows: {
                      type: "array",
                      maxItems: 10000,
                      items: {
                        $ref: "#/$defs/Json",
                      },
                    },
                    truncated: {
                      type: "boolean",
                    },
                  },
                  required: ["rows", "truncated"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "artifacts.begin",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    uploadId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                    artifact: {
                      $ref: "#/$defs/PendingArtifact",
                    },
                  },
                  required: ["uploadId", "artifact"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "artifacts.write",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    acceptedBytes: {
                      type: "integer",
                      minimum: 0,
                      maximum: 16777216,
                    },
                  },
                  required: ["acceptedBytes"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "artifacts.commit",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  $ref: "#/$defs/ReadyArtifact",
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "artifacts.read",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    artifact: {
                      $ref: "#/$defs/ReadyArtifact",
                    },
                    bytesBase64: {
                      type: "string",
                      minLength: 0,
                      maxLength: 22369624,
                      pattern: "^[A-Za-z0-9+/]*={0,2}$",
                    },
                    nextOffset: {
                      anyOf: [
                        {
                          type: "integer",
                          minimum: 0,
                          maximum: 16777216,
                        },
                        {
                          type: "null",
                        },
                      ],
                    },
                  },
                  required: ["artifact", "bytesBase64", "nextOffset"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "memory.read",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  anyOf: [
                    {
                      $ref: "#/$defs/MemoryItem",
                    },
                    {
                      type: "null",
                    },
                  ],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "memory.search",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "array",
                  maxItems: 1000,
                  items: {
                    $ref: "#/$defs/MemoryItem",
                  },
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "memory.remember",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  $ref: "#/$defs/MemoryItem",
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "memory.forget",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    revision: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                    deleted: {
                      type: "boolean",
                      const: true,
                    },
                  },
                  required: ["revision", "deleted"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "collaboration.discover",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      agentId: {
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
                      capabilities: {
                        type: "array",
                        maxItems: 1024,
                        items: {
                          type: "string",
                          minLength: 1,
                          maxLength: 128,
                          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                        },
                      },
                    },
                    required: ["agentId", "version", "capabilities"],
                  },
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "collaboration.invoke",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    runId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                  },
                  required: ["runId"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "collaboration.wait",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    completedRunIds: {
                      type: "array",
                      maxItems: 1024,
                      items: {
                        type: "string",
                        minLength: 1,
                        maxLength: 128,
                        pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                      },
                    },
                  },
                  required: ["completedRunIds"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "collaboration.result",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    status: {
                      type: "string",
                      enum: ["running", "waiting", "completed", "failed", "cancelled"],
                    },
                    output: {
                      $ref: "#/$defs/Json",
                    },
                    artifacts: {
                      type: "array",
                      maxItems: 1024,
                      items: {
                        $ref: "#/$defs/Artifact",
                      },
                    },
                  },
                  required: ["status", "artifacts"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "sandbox.execute",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    executionId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                    exitCode: {
                      anyOf: [
                        {
                          type: "integer",
                          minimum: 0,
                          maximum: 255,
                        },
                        {
                          type: "null",
                        },
                      ],
                    },
                    artifacts: {
                      type: "array",
                      maxItems: 1024,
                      items: {
                        $ref: "#/$defs/Artifact",
                      },
                    },
                  },
                  required: ["executionId", "exitCode", "artifacts"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "sandbox.pause",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    checkpointId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                  },
                  required: ["checkpointId"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
    {
      type: "object",
      additionalProperties: false,
      properties: {
        apiVersion: {
          type: "string",
          const: "port-result.v1",
          maxLength: 64,
        },
        callId: {
          type: "string",
          minLength: 1,
          maxLength: 128,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
        method: {
          type: "string",
          const: "sandbox.resume",
          maxLength: 64,
        },
        outcome: {
          oneOf: [
            {
              type: "object",
              additionalProperties: false,
              properties: {
                status: {
                  type: "string",
                  const: "ok",
                  maxLength: 64,
                },
                output: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    executionId: {
                      type: "string",
                      minLength: 1,
                      maxLength: 128,
                      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                  },
                  required: ["executionId"],
                },
                evidence: {
                  type: "array",
                  maxItems: 1024,
                  items: {
                    $ref: "#/$defs/Evidence",
                  },
                },
                limitations: {
                  type: "array",
                  maxItems: 128,
                  items: {
                    type: "string",
                    minLength: 0,
                    maxLength: 2048,
                  },
                },
              },
              required: ["status", "output", "evidence", "limitations"],
            },
            {
              $ref: "#/$defs/NonSuccess",
            },
          ],
        },
      },
      required: ["apiVersion", "callId", "method", "outcome"],
    },
  ],
} as const;
