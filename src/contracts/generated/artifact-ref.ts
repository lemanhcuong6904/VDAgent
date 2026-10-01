// Generated from schemas/artifact-ref.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type ArtifactRef =
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
export const ArtifactRefSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:artifact-ref:v1",
  title: "ArtifactRef",
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
      required: ["id", "workspaceId", "ownerRunId", "kind", "version", "status", "sha256", "bytes"],
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
} as const;
