// Generated from schemas/wait-request.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type WaitRequest =
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
export const WaitRequestSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:wait-request:v1",
  title: "WaitRequest",
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
      required: ["reason", "idempotencyKey", "expiresAt", "requestId", "safeMessage", "actionId"],
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
} as const;
