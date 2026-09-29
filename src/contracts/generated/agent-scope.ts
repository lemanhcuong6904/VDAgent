// Generated from schemas/agent-scope.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type AgentScope = {
  tenantId: string;
  workspaceId: string;
  actorId: string;
  audience: string;
  taskId: string;
  runId: string;
  attemptId: string;
  agentId: string;
  agentVersion: string;
  policyRevision: string;
  fence: string;
  traceId: string;
};
export const AgentScopeSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:agent-scope:v1",
  title: "AgentScope",
  type: "object",
  additionalProperties: false,
  properties: {
    tenantId: {
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
    actorId: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    },
    audience: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    },
    taskId: {
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
    agentId: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    },
    agentVersion: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^\\d+\\.\\d+\\.\\d+(?:-[A-Za-z0-9.-]+)?$",
    },
    policyRevision: {
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
    traceId: {
      type: "string",
      minLength: 1,
      maxLength: 128,
      pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    },
  },
  required: [
    "tenantId",
    "workspaceId",
    "actorId",
    "audience",
    "taskId",
    "runId",
    "attemptId",
    "agentId",
    "agentVersion",
    "policyRevision",
    "fence",
    "traceId",
  ],
} as const;
