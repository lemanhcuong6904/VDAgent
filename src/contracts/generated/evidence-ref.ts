// Generated from schemas/evidence-ref.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.

export type EvidenceRef = {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  fence: string;
  policyRevision: string;
  kind: "claim" | "process_exit" | "observer_hint" | "receipt";
  verification: "unverified" | "verified" | "unavailable";
};
export const EvidenceRefSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:evidence-ref:v1",
  title: "EvidenceRef",
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
} as const;
