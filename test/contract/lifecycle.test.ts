import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import { describe, expect, it } from "vitest";
import { CheckpointRefSchema, WaitRequestSchema } from "../../src/contracts/index.js";

const ajv = new Ajv2020({ strict: true });
ajv.addFormat("date-time", fullFormats["date-time"]);
describe("checkpoint and wait wire contracts", () => {
  it("requires lineage, ownership, hash, size and fencing metadata", () => {
    const validate = ajv.compile(CheckpointRefSchema);
    const checkpoint = {
      id: "c1",
      schemaVersion: "state.v1",
      workspaceId: "w",
      runId: "r",
      attemptId: "a",
      fence: "1",
      parentId: null,
      baseId: null,
      stateSha256: "a".repeat(64),
      bytes: 1,
      createdAt: "2026-09-26T00:00:00Z",
    };
    expect(validate(checkpoint)).toBe(true);
    expect(validate({ ...checkpoint, baseId: undefined })).toBe(false);
    expect(validate({ ...checkpoint, stateSha256: "invalid" })).toBe(false);
    expect(validate({ ...checkpoint, bytes: 16777217 })).toBe(false);
    expect(validate({ ...checkpoint, fence: 0 })).toBe(false);
  });
  it("requires correlated wait targets and rejects mismatched reason payloads", () => {
    const validate = ajv.compile(WaitRequestSchema);
    const common = { idempotencyKey: "wait-1", expiresAt: "2026-09-26T00:00:00Z" };
    for (const payload of [
      { reason: "input", requestId: "q", safeMessage: "Supply input" },
      { reason: "approval", requestId: "q", safeMessage: "Approve action", actionId: "action" },
      { reason: "children", runIds: ["child"] },
      { reason: "tool", executionId: "tool-1" },
      { reason: "peer", messageId: "message-1" },
    ])
      expect(validate({ ...common, ...payload })).toBe(true);
    expect(validate({ ...common, reason: "children", runIds: [] })).toBe(false);
    expect(validate({ ...common, reason: "children", runIds: Array(65).fill("r") })).toBe(false);
    expect(validate({ ...common, reason: "approval", messageId: "message-1" })).toBe(false);
    expect(validate({ ...common, reason: "peer", messageId: "message-1", authorized: true })).toBe(
      false,
    );
  });
});
