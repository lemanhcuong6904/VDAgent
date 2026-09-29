// Generated from schemas/usage-summary.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type UsageSummary = {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  modelCalls: number;
  toolCalls: number;
  durationMs: number;
  estimatedCostUsd: number;
};
export const UsageSummarySchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:usage-summary:v1",
  title: "UsageSummary",
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
} as const;
