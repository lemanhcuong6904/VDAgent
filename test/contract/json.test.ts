import { expect, it } from "vitest";
import { encodeBoundedJson } from "../../src/testkit/json.js";

it("counts aggregate UTF-8 bytes and depth while preserving valid JSON", () => {
  expect(encodeBoundedJson({ a: [1, null, "é"] }, 64)).toBe(JSON.stringify({ a: [1, null, "é"] }));
  expect(() => encodeBoundedJson("😀", 5)).toThrow("json_byte_limit");
  expect(() => encodeBoundedJson({ a: { b: 1 } }, 64, 1)).toThrow("json_depth_limit");
  expect(() => encodeBoundedJson({ a: "1234", b: "5678" }, 20)).toThrow("json_byte_limit");
});
it("rejects cycles, sparse arrays, nonfinite numbers and implicit coercion", () => {
  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  for (const value of [
    cyclic,
    new Array(2),
    NaN,
    Infinity,
    undefined,
    new Date(),
    { a: undefined },
  ])
    expect(() => encodeBoundedJson(value, 1024)).toThrow();
  const shared = { a: 1 };
  expect(encodeBoundedJson([shared, shared], 64)).toBe('[{"a":1},{"a":1}]');
});
it("does not execute getters or custom serialization hooks", () => {
  let calls = 0;
  expect(() =>
    encodeBoundedJson(
      {
        get value() {
          calls++;
          return 1;
        },
      },
      64,
    ),
  ).toThrow();
  expect(() =>
    encodeBoundedJson(
      {
        toJSON() {
          calls++;
          return null;
        },
      },
      64,
    ),
  ).toThrow();
  expect(calls).toBe(0);
});
