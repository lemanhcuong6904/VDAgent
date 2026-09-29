import assert from "node:assert/strict";
import { test } from "node:test";
import { generateContracts, renderType } from "../generate-contracts.mjs";

test("type generator retains optional fields, literal unions and nested shapes", () => {
  const type = renderType({
    type: "object",
    additionalProperties: false,
    required: ["status"],
    properties: {
      status: { type: "string", enum: ["ready", "unknown"] },
      count: { type: ["integer", "null"] },
    },
  });
  assert.match(type, /"status": "ready" \| "unknown"/);
  assert.match(type, /"count"\?: number \| null/);
  assert.equal(
    renderType({ oneOf: [{ type: "string" }, { type: "array", items: { type: "integer" } }] }),
    "(string | Array<number>)",
  );
});

test("generator fails closed on unsupported structural semantics", () => {
  assert.throws(() => renderType({ type: "object", additionalProperties: true }), /closed/);
  assert.throws(() => renderType({ $ref: "#/$defs/a" }), /resolution/);
  assert.throws(
    () => renderType({ type: "object", patternProperties: { a: { type: "string" } } }),
    /Unsupported/,
  );
  assert.throws(() => renderType({ allOf: [{ type: "string" }] }), /Unsupported/);
});

test("local definitions support recursive JSON shapes without following remote references", () => {
  const definitions = {
    Value: { anyOf: [{ type: "string" }, { type: "array", items: { $ref: "#/$defs/Value" } }] },
  };
  assert.equal(
    renderType(definitions.Value, definitions, "Result"),
    "(string | Array<ResultValue>)",
  );
  assert.equal(renderType({ $ref: "#/$defs/Value" }, definitions, "Result"), "ResultValue");
  assert.throws(
    () => renderType({ $ref: "https://example.invalid/schema" }, definitions),
    /resolution/,
  );
  assert.throws(
    () => renderType({ $ref: "#/$defs/Value", type: "string" }, definitions),
    /siblings/,
  );
  assert.throws(() => renderType({ $ref: "#/$defs/Missing" }, definitions), /resolution/);
});

test("scoped generation rejects unknown names and receipt schemas instead of silently skipping", () => {
  assert.throws(
    () => generateContracts(process.cwd(), true, ["../port-call.schema.json"]),
    /Unknown public contract selection/,
  );
  assert.throws(
    () => generateContracts(process.cwd(), true, ["missing.schema.json"]),
    /Unknown public contract selection/,
  );
  assert.throws(
    () => generateContracts(process.cwd(), true, ["execution-receipt.schema.json"]),
    /Unknown public contract selection/,
  );
});
