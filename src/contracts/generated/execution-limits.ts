// Generated from schemas/execution-limits.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type ExecutionLimits = {
  timeoutMs: number;
  maxInputBytes: number;
  maxOutputBytes: number;
  maxEventBytes: number;
  maxCheckpointBytes: number;
  maxModelCalls: number;
  maxToolCalls: number;
  maxChildRuns: number;
  maxDepth: number;
  maxCostUsd: number;
};
export const ExecutionLimitsSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:execution-limits:v1",
  title: "ExecutionLimits",
  type: "object",
  additionalProperties: false,
  properties: {
    timeoutMs: {
      type: "integer",
      minimum: 1,
      maximum: 86400000,
    },
    maxInputBytes: {
      type: "integer",
      minimum: 1,
      maximum: 16777216,
    },
    maxOutputBytes: {
      type: "integer",
      minimum: 1,
      maximum: 16777216,
    },
    maxEventBytes: {
      type: "integer",
      minimum: 1,
      maximum: 16777216,
    },
    maxCheckpointBytes: {
      type: "integer",
      minimum: 1,
      maximum: 16777216,
    },
    maxModelCalls: {
      type: "integer",
      minimum: 0,
      maximum: 10000,
    },
    maxToolCalls: {
      type: "integer",
      minimum: 0,
      maximum: 10000,
    },
    maxChildRuns: {
      type: "integer",
      minimum: 0,
      maximum: 1024,
    },
    maxDepth: {
      type: "integer",
      minimum: 0,
      maximum: 64,
    },
    maxCostUsd: {
      type: "number",
      minimum: 0,
      maximum: 1000000,
    },
  },
  required: [
    "timeoutMs",
    "maxInputBytes",
    "maxOutputBytes",
    "maxEventBytes",
    "maxCheckpointBytes",
    "maxModelCalls",
    "maxToolCalls",
    "maxChildRuns",
    "maxDepth",
    "maxCostUsd",
  ],
} as const;
