import { expect, it } from "vitest";
import { ManualClock } from "../../src/testkit/call.js";
import type { WarehouseQueryHandler } from "../../src/testkit/warehouse.js";
import { createFakeWarehousePort } from "../../src/testkit/warehouse.js";

function handlerFixture(execute: WarehouseQueryHandler["execute"], clock = new ManualClock()) {
  return createFakeWarehousePort({
    fixtures: [
      { sourceId: "s", displayName: "Source", datasetId: "d", queryId: "q", columns: [], rows: [] },
    ],
    clock,
    maxRows: 10,
    maxBytes: 512,
    maxInputBytes: 1024,
    handlers: new Map([
      ["q", { parameterSchema: { type: "object", additionalProperties: false }, execute }],
    ]),
  });
}

it("aborts a timed-out query and ignores a late successful result", async () => {
  const clock = new ManualClock();
  let received!: AbortSignal;
  let complete!: (rows: []) => void;
  const port = handlerFixture(async (_parameters, signal) => {
    received = signal;
    return new Promise<[]>((resolve) => {
      complete = resolve;
    });
  }, clock);
  const pending = port.query(request, options);
  clock.advance(10);
  expect(await pending).toMatchObject({
    status: "failed",
    error: { code: "deadline_after_dispatch" },
  });
  expect(received.aborted).toBe(true);
  complete([]);
  expect(await pending).toMatchObject({ status: "failed" });
  expect(clock.pendingTimers).toBe(0);
});

it("bounds provider results before truncation and redacts handler errors", async () => {
  const oversized = handlerFixture(async () => [1, "x".repeat(513)]);
  expect(await oversized.query(request, options)).toMatchObject({ status: "failed" });
  const failed = handlerFixture(async () => {
    throw new Error("private credential detail");
  });
  const result = await failed.query(request, options);
  expect(result).toMatchObject({ status: "failed", error: { safeMessage: "operation_failed" } });
  expect(JSON.stringify(result)).not.toContain("private credential");
});

it("does not dispatch cancelled requests", async () => {
  let calls = 0;
  const port = handlerFixture(async () => {
    calls++;
    return [];
  });
  const controller = new AbortController();
  controller.abort();
  expect(await port.query(request, { ...options, signal: controller.signal })).toMatchObject({
    status: "failed",
    error: { code: "cancelled_before_dispatch" },
  });
  expect(calls).toBe(0);
});

it("validates query parameters before dispatch and isolates handler input", async () => {
  let calls = 0;
  const port = createFakeWarehousePort({
    fixtures: [
      { sourceId: "s", displayName: "Source", datasetId: "d", queryId: "q", columns: [], rows: [] },
    ],
    clock: new ManualClock(),
    maxRows: 10,
    maxBytes: 4096,
    maxInputBytes: 1024,
    handlers: new Map([
      [
        "q",
        {
          parameterSchema: {
            type: "object",
            properties: { value: { type: "integer" } },
            required: ["value"],
            additionalProperties: false,
          },
          execute: async (parameters) => {
            calls++;
            const value = parameters.value;
            parameters.value = 99;
            return [{ value }];
          },
        },
      ],
    ]),
  });
  const parameters = { value: 7 };
  expect(await port.query({ ...request, parameters }, options)).toMatchObject({
    status: "ok",
    output: { rows: [{ value: 7 }] },
  });
  expect(parameters.value).toBe(7);
  expect(await port.query({ ...request, parameters: { value: "bad" } }, options)).toMatchObject({
    status: "denied",
  });
  expect(calls).toBe(1);
});

const options = { signal: new AbortController().signal, deadline: 10 };
const request = { queryId: "q", parameters: {}, maxRows: 1, maxBytes: 128, idempotencyKey: "k" };
const fixture = () =>
  createFakeWarehousePort({
    fixtures: [
      {
        sourceId: "s",
        displayName: "Source",
        datasetId: "d",
        queryId: "q",
        columns: [{ name: "value", type: "number" }],
        rows: [{ value: 1 }, { value: 2 }],
      },
    ],
    clock: new ManualClock(),
    maxRows: 10,
    maxBytes: 4096,
    maxInputBytes: 1024,
  });
it("returns only registered catalog/data and reports row truncation", async () => {
  const port = fixture();
  expect(await port.catalog(options)).toMatchObject({ status: "ok", output: [{ id: "s" }] });
  expect(await port.describe({ sourceId: "s", datasetId: "d" }, options)).toMatchObject({
    status: "ok",
  });
  expect(await port.query(request, options)).toMatchObject({
    status: "ok",
    output: { rows: [{ value: 1 }], truncated: true },
  });
  expect(await port.query({ ...request, maxBytes: 2 }, options)).toMatchObject({
    status: "failed",
    error: { code: "output_limit" },
  });
});
it("rejects raw SQL, unknown query IDs, parameter misuse and expanded limits", async () => {
  const port = fixture();
  for (const change of [
    { sql: "select 1" },
    { queryId: "other" },
    { parameters: { unsafe: "x" } },
    { maxRows: 11 },
    { maxBytes: 4097 },
  ]) {
    expect(await port.query({ ...request, ...change }, options)).toMatchObject({
      status: "denied",
    });
  }
  expect(await port.describe({ sourceId: "other", datasetId: "d" }, options)).toMatchObject({
    status: "denied",
  });
});
