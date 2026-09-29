import { expect, it } from "vitest";
import type { MemoryPort, PortOutcome } from "../../src/contracts/ports.js";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeMemoryPort } from "../../src/testkit/memory.js";

const iso = (ms: number) => new Date(ms).toISOString();
const options = { signal: new AbortController().signal, deadline: 1000 };
const request: Parameters<MemoryPort["remember"]>[0] = {
  id: "note",
  expectedRevision: null,
  content: { text: "untrusted fact" },
  scope: "agent",
  audience: "internal",
  sensitivity: "private",
  expiresAt: null,
  provenance: [],
  idempotencyKey: "create",
};
const search = { query: "", scope: "agent" as const, limit: 5, maxBytes: 4096, asOf: iso(0) };
function setup(overrides: Partial<Parameters<typeof createFakeMemoryPort>[0]> = {}) {
  return createFakeMemoryPort({
    workspaceId: "workspace",
    audience: "internal",
    scopes: ["agent", "workspace"],
    sensitivities: ["private"],
    clock: new ManualClock(),
    maxBytes: 4096,
    maxItems: 5,
    maxMutations: 20,
    ...overrides,
  });
}
function output<T>(result: PortOutcome<T>): T {
  expect(result.status).toBe("ok");
  if (result.status !== "ok") throw new Error("Expected success");
  return result.output;
}
it("keeps content untrusted, isolated and snapshot-safe", async () => {
  const port = setup();
  const input = structuredClone(request);
  const saved = output(await port.remember(input, options));
  input.content = "changed caller";
  saved.content = "changed response";
  expect(output(await port.read({ id: "note" }, options))).toMatchObject({
    content: request.content,
    trust: "untrusted",
    revision: "1",
  });
  expect(output(await setup().read({ id: "note" }, options))).toBeNull();
});
it("serializes concurrent CAS writes and canonical idempotent replay", async () => {
  const port = setup();
  const writes = await Promise.all([
    port.remember(request, options),
    port.remember({ ...request, content: "race", idempotencyKey: "race" }, options),
  ]);
  expect(writes.map((result) => result.status)).toEqual(["ok", "denied"]);
  expect(writes[1]).toMatchObject({ error: { code: "revision_conflict" } });
  const reordered = {
    ...request,
    content: { b: 2, a: 1 },
    expectedRevision: "1",
    idempotencyKey: "edit",
  };
  const edit = await port.remember(reordered, options);
  expect(await port.remember({ ...reordered, content: { a: 1, b: 2 } }, options)).toEqual(edit);
  expect(await port.remember({ ...reordered, content: "changed" }, options)).toMatchObject({
    status: "denied",
    error: { code: "idempotency_conflict" },
  });
});
it("honors temporal cutoffs without resurrecting expired revisions", async () => {
  const clock = new ManualClock();
  const port = setup({ clock });
  await port.remember(request, options);
  clock.advance(10);
  const edit = {
    ...request,
    expectedRevision: "1",
    content: "new",
    expiresAt: iso(20),
    idempotencyKey: "edit",
  };
  await port.remember(edit, options);
  expect(output(await port.search(search, options))[0].content).toEqual(request.content);
  expect(output(await port.search({ ...search, asOf: iso(10) }, options))[0].content).toBe("new");
  clock.advance(10);
  expect(output(await port.read({ id: "note" }, options))).toBeNull();
  expect(output(await port.search({ ...search, asOf: iso(20) }, options))).toEqual([]);
  expect(output(await port.search({ ...search, asOf: iso(10) }, options))).toEqual([]);
  expect(await port.remember(edit, options)).toMatchObject({
    status: "denied",
    error: { code: "replay_content_unavailable" },
  });
  expect(await port.remember({ ...request, idempotencyKey: "recreate" }, options)).toMatchObject({
    status: "denied",
    error: { code: "revision_conflict" },
  });
});
it("deletes all history, preserves a CAS tombstone and never replays forgotten content", async () => {
  const port = setup();
  await port.remember(request, options);
  expect(
    await port.forget({ id: "note", expectedRevision: "stale", idempotencyKey: "stale" }, options),
  ).toMatchObject({ status: "denied" });
  const deletion = { id: "note", expectedRevision: "1", idempotencyKey: "delete" };
  const deleted = await port.forget(deletion, options);
  expect(output(deleted)).toEqual({ revision: "2", deleted: true });
  expect(await port.forget(deletion, options)).toEqual(deleted);
  expect(output(await port.search(search, options))).toEqual([]);
  expect(await port.remember(request, options)).toMatchObject({
    status: "denied",
    error: { code: "replay_content_unavailable" },
  });
  expect(await port.remember({ ...request, idempotencyKey: "new" }, options)).toMatchObject({
    status: "denied",
  });
  expect(
    output(
      await port.remember(
        { ...request, expectedRevision: "2", idempotencyKey: "restore" },
        options,
      ),
    ),
  ).toMatchObject({ revision: "3" });
});
it("rejects unknown authority, ungranted scope, malformed evidence and invalid retention", async () => {
  const port = setup();
  const changes = [
    { workspaceId: "other" },
    { trust: "trusted" },
    { audience: "other" },
    { scope: "user" },
    { sensitivity: "public" },
    { expiresAt: "tomorrow" },
    { expiresAt: iso(0) },
    { provenance: [{}] },
    {
      provenance: [
        {
          id: "e",
          workspaceId: "other",
          runId: "r",
          attemptId: "a",
          fence: "1",
          policyRevision: "p",
          kind: "claim",
          verification: "unverified",
        },
      ],
    },
  ];
  for (const change of changes)
    expect(await port.remember({ ...request, ...change } as typeof request, options)).toMatchObject(
      { status: "denied" },
    );
  expect(output(await port.read({ id: "note" }, options))).toBeNull();
  expect(await port.search({ ...search, asOf: iso(1) }, options)).toMatchObject({
    status: "denied",
  });
  expect(
    await port.read({ id: "note", audience: "other" } as { id: string }, options),
  ).toMatchObject({ status: "denied" });
});
it("bounds UTF-8 input, result bytes, identity slots and mutation history", async () => {
  const port = setup({ maxItems: 1, maxMutations: 2 });
  expect(await port.remember({ ...request, content: "é".repeat(4096) }, options)).toMatchObject({
    status: "denied",
  });
  await port.remember(request, options);
  expect(await port.search({ ...search, limit: 1, maxBytes: 2 }, options)).toMatchObject({
    status: "failed",
    error: { code: "output_limit" },
  });
  expect(
    await port.remember({ ...request, id: "other", idempotencyKey: "other" }, options),
  ).toMatchObject({ status: "denied", error: { code: "item_limit" } });
  expect(
    await port.forget({ id: "note", expectedRevision: "1", idempotencyKey: "delete" }, options),
  ).toMatchObject({ status: "denied", error: { code: "mutation_limit" } });
});
it("does not reserve writes before dispatch and retains unknown outcomes after timeout", async () => {
  const clock = new ManualClock();
  let calls = 0;
  let release!: () => void;
  let received!: AbortSignal;
  const port = setup({
    clock,
    before: async (operation, signal) => {
      if (operation !== "remember") return;
      calls++;
      received = signal;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const controller = new AbortController();
  controller.abort();
  expect(await port.remember(request, { ...options, signal: controller.signal })).toMatchObject({
    status: "denied",
  });
  expect(await port.remember(request, { ...options, deadline: 0 })).toMatchObject({
    status: "denied",
  });
  expect(calls).toBe(0);
  const pending = port.remember(request, { ...options, deadline: 10 });
  clock.advance(10);
  expect(await pending).toMatchObject({
    status: "unknown",
    error: { code: "deadline_after_dispatch", retryable: false },
  });
  expect(received.aborted).toBe(true);
  release();
  expect(await port.remember(request, options)).toMatchObject({ status: "unknown" });
  expect(calls).toBe(1);
  expect(output(await port.read({ id: "note" }, options))).toBeNull();
  expect(clock.pendingTimers).toBe(0);
});
it("redacts fault details and cancels in-flight reads", async () => {
  const clock = new ManualClock();
  const port = setup({
    clock,
    before: async () => {
      throw new Error("private secret");
    },
  });
  const failed = await port.read({ id: "note" }, options);
  expect(failed).toMatchObject({ status: "failed", error: { safeMessage: "operation_failed" } });
  expect(JSON.stringify(failed)).not.toContain("private secret");
  const hanging = setup({ clock, before: async () => new Promise<void>(() => {}) });
  const controller = new AbortController();
  const pending = hanging.read({ id: "note" }, { ...options, signal: controller.signal });
  controller.abort();
  expect(await pending).toMatchObject({
    status: "failed",
    error: { code: "cancelled_after_dispatch" },
  });
  expect(clock.pendingTimers).toBe(0);
});

it("bounds a concurrent replay by its own deadline without cancelling the original", async () => {
  const clock = new ManualClock();
  let release!: () => void;
  let calls = 0;
  const port = setup({
    clock,
    before: async () => {
      calls++;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const original = port.remember(request, options);
  const replay = port.remember(request, { ...options, deadline: 10 });
  clock.advance(10);
  expect(await replay).toMatchObject({
    status: "unknown",
    error: { code: "deadline_after_dispatch" },
  });
  release();
  expect(output(await original)).toMatchObject({ revision: "1" });
  expect(output(await port.remember(request, options))).toMatchObject({ revision: "1" });
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});
