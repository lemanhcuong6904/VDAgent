import { expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/generated/agent-scope.js";
import type { PortOutcome } from "../../src/contracts/ports.js";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeSandboxPort, type SandboxFixture } from "../../src/testkit/sandbox.js";

const scope: AgentScope = {
  tenantId: "t",
  workspaceId: "w",
  actorId: "a",
  audience: "internal",
  taskId: "task",
  runId: "r",
  attemptId: "attempt",
  agentId: "agent",
  agentVersion: "1.0.0",
  policyRevision: "p",
  fence: "1",
  traceId: "trace",
};
const options = { signal: new AbortController().signal, deadline: 1000 };
const request = {
  commandId: "analyze",
  arguments: { value: 1 },
  inputArtifacts: ["input"],
  credentialRefs: ["vault-ref"],
  maxOutputBytes: 64,
  idempotencyKey: "execute",
};
function setup(
  run: SandboxFixture["run"] = async () => ({ exitCode: null, output: "" }),
  overrides: Partial<Parameters<typeof createFakeSandboxPort>[0]> = {},
) {
  return createFakeSandboxPort({
    scope,
    clock: new ManualClock(),
    commands: [
      {
        commandId: "analyze",
        argumentSchema: {
          type: "object",
          properties: { value: { type: "integer" } },
          required: ["value"],
          additionalProperties: false,
        },
        artifacts: [],
        run,
      },
    ],
    inputArtifacts: ["input"],
    credentialRefs: ["vault-ref"],
    maxInstances: 3,
    maxMutations: 20,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
    ...overrides,
  });
}
function output<T>(result: PortOutcome<T>): T {
  expect(result.status).toBe("ok");
  if (result.status !== "ok") throw new Error("Expected success");
  return result.output;
}
it("pauses only running instances and resumes with fresh identities and idempotency", async () => {
  let calls = 0;
  const port = setup(async () => {
    calls++;
    return { exitCode: null, output: "" };
  });
  const execution = output(await port.execute(request, options));
  expect(await port.execute(request, options)).toMatchObject({ output: execution });
  const pause = { executionId: execution.executionId, idempotencyKey: "pause" };
  const checkpoint = output(await port.pause(pause, options));
  expect(output(await port.pause(pause, options))).toEqual(checkpoint);
  expect(await port.pause({ ...pause, idempotencyKey: "pause-again" }, options)).toMatchObject({
    status: "denied",
  });
  const resume = { checkpointId: checkpoint.checkpointId, idempotencyKey: "resume" };
  const restored = output(await port.resume(resume, options));
  expect(restored.executionId).not.toBe(execution.executionId);
  expect(output(await port.resume(resume, options))).toEqual(restored);
  const branch = output(await port.resume({ ...resume, idempotencyKey: "branch" }, options));
  expect(branch.executionId).not.toBe(restored.executionId);
  expect(await port.resume({ ...resume, idempotencyKey: "overflow" }, options)).toMatchObject({
    status: "denied",
    error: { code: "instance_limit" },
  });
  expect(
    await port.pause({ ...pause, idempotencyKey: "source-still-paused" }, options),
  ).toMatchObject({ status: "denied" });
  expect(calls).toBe(1);
});
it("enforces command, schema, artifact and credential grants before dispatch", async () => {
  let calls = 0;
  const port = setup(async () => {
    calls++;
    return { exitCode: 0, output: "" };
  });
  const changes = [
    { commandId: "shell" },
    { arguments: { value: "bad" } },
    { arguments: { value: 1, shell: "evil" } },
    { inputArtifacts: ["other"] },
    { credentialRefs: ["raw-secret"] },
    { workspaceId: "other" },
    { maxOutputBytes: 4097 },
  ];
  for (const [index, change] of changes.entries())
    expect(
      await port.execute(
        { ...request, ...change, idempotencyKey: `bad-${index}` } as typeof request,
        options,
      ),
    ).toMatchObject({ status: "denied" });
  expect(calls).toBe(0);
  const execution = output(await port.execute(request, options));
  expect(execution.exitCode).toBe(0);
  expect(
    await port.pause({ executionId: execution.executionId, idempotencyKey: "pause" }, options),
  ).toMatchObject({ status: "denied" });
  expect(
    await setup().pause({ executionId: execution.executionId, idempotencyKey: "other" }, options),
  ).toMatchObject({ status: "denied" });
  expect(
    await setup().resume({ checkpointId: "fake-checkpoint-1", idempotencyKey: "other" }, options),
  ).toMatchObject({ status: "denied" });
});
it("caps UTF-8 fixture output as an unknown effect and never promotes process exit to proof", async () => {
  const port = setup(async () => ({ exitCode: 0, output: "éé" }));
  const result = await port.execute({ ...request, maxOutputBytes: 3 }, options);
  expect(result).toMatchObject({
    status: "unknown",
    error: { code: "output_limit", retryable: false },
  });
  expect(await port.execute({ ...request, maxOutputBytes: 3 }, options)).toEqual(result);
  const success = await setup(async () => ({ exitCode: 2, output: "" })).execute(request, options);
  expect(success).toMatchObject({ status: "ok", output: { exitCode: 2 }, evidence: [] });
});
it("rejects cancelled/expired requests and aborts an in-flight fixture without relaunch", async () => {
  const clock = new ManualClock();
  let calls = 0;
  let received!: AbortSignal;
  let release!: () => void;
  const port = setup(
    async (_args, signal) => {
      calls++;
      received = signal;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return { exitCode: 0, output: "" };
    },
    { clock },
  );
  const controller = new AbortController();
  controller.abort();
  expect(await port.execute(request, { ...options, signal: controller.signal })).toMatchObject({
    status: "denied",
  });
  expect(await port.execute(request, { ...options, deadline: 0 })).toMatchObject({
    status: "denied",
  });
  expect(calls).toBe(0);
  const pending = port.execute(request, { ...options, deadline: 10 });
  await Promise.resolve();
  clock.advance(10);
  expect(await pending).toMatchObject({ status: "unknown" });
  expect(received.aborted).toBe(true);
  release();
  expect(await port.execute(request, options)).toMatchObject({ status: "unknown" });
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});
it("uses a duplicate caller's deadline without interrupting the original execution", async () => {
  const clock = new ManualClock();
  let release!: () => void;
  const port = setup(
    async () => {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return { exitCode: 0, output: "" };
    },
    { clock },
  );
  const original = port.execute(request, options);
  const replay = port.execute(request, { ...options, deadline: 10 });
  await Promise.resolve();
  clock.advance(10);
  expect(await replay).toMatchObject({
    status: "unknown",
    error: { code: "deadline_after_dispatch" },
  });
  release();
  expect(await original).toMatchObject({ status: "ok" });
  expect(clock.pendingTimers).toBe(0);
});
it("redacts fixture exceptions, checks mutation limits and snapshots fixture policy", async () => {
  const failure = await setup(async () => {
    throw new Error("secret");
  }).execute(request, options);
  expect(failure).toMatchObject({ status: "unknown", error: { safeMessage: "operation_failed" } });
  expect(JSON.stringify(failure)).not.toContain("secret");
  const grants = ["vault-ref"];
  const port = setup(undefined, { credentialRefs: grants, maxMutations: 1 });
  grants.push("other");
  expect(await port.execute({ ...request, credentialRefs: ["other"] }, options)).toMatchObject({
    status: "denied",
  });
  expect(await port.execute({ ...request, idempotencyKey: "new" }, options)).toMatchObject({
    status: "denied",
    error: { code: "execution_limit" },
  });
  expect(() =>
    setup(undefined, {
      commands: [
        {
          commandId: "bad",
          argumentSchema: true,
          artifacts: [
            {
              id: "a",
              workspaceId: "other",
              ownerRunId: "r",
              kind: "text",
              version: "1",
              status: "ready",
              bytes: 0,
              sha256: "a".repeat(64),
            },
          ],
          run: async () => ({ exitCode: 0, output: "" }),
        },
      ],
    }),
  ).toThrow("Invalid sandbox artifact fixture");
});
