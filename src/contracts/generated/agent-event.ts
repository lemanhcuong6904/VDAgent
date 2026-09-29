// Generated from schemas/agent-event.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.
type AgentEventEvidence = {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  fence: string;
  policyRevision: string;
  kind: "claim" | "process_exit" | "observer_hint" | "receipt";
  verification: "unverified" | "verified" | "unavailable";
};
export type AgentEvent = {
  version: "agent-event.v1";
  id: string;
  sequence: number;
  type: "progress" | "warning";
  safeMessage: string;
  evidence: Array<AgentEventEvidence>;
};
export const AgentEventSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:agent-event:v1",
  title: "AgentEvent",
  type: "object",
  additionalProperties: false,
  properties: {
    version: {
      type: "string",
      const: "agent-event.v1",
      maxLength: 32,
    },
    id: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    },
    sequence: {
      type: "integer",
      minimum: 1,
      maximum: 9007199254740991,
    },
    type: {
      type: "string",
      enum: ["progress", "warning"],
    },
    safeMessage: {
      type: "string",
      minLength: 1,
      maxLength: 2048,
    },
    evidence: {
      type: "array",
      maxItems: 128,
      items: {
        $ref: "#/$defs/Evidence",
      },
    },
  },
  required: ["version", "id", "sequence", "type", "safeMessage", "evidence"],
  $defs: {
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
  },
} as const;
