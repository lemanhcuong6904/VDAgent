// Generated from schemas/structured-error.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type StructuredError = {
  code: string;
  class: "validation" | "policy" | "transient" | "permanent" | "unknown";
  retryable: boolean;
  safeMessage: string;
  correlationId: string;
};
export const StructuredErrorSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:structured-error:v1",
  title: "StructuredError",
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
} as const;
