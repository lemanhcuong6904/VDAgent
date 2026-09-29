import { describe, expect, it, vi } from "vitest";
import { DockerSandboxProvider, type DockerTransport } from "../src/docker-sandbox.js";
import type { ToolScope } from "../src/tool-pool.js";

function scope(signal: AbortSignal = new AbortController().signal): ToolScope {
  return {
    userId: "user-1",
    spaceId: "space-1",
    agentId: "agent-1",
    signal,
  };
}

function readyTransport(stream: DockerTransport["stream"]): DockerTransport & {
  request: ReturnType<typeof vi.fn>;
} {
  return {
    request: vi.fn(async (path: string) => {
      if (path.endsWith("/json") && path.startsWith("/containers/")) {
        return { State: { Running: true } };
      }
      if (path.startsWith("/containers/") && path.endsWith("/exec")) {
        return { Id: "exec-1" };
      }
      if (path === "/exec/exec-1/json") return { ExitCode: 0 };
      return {};
    }),
    stream,
  };
}

describe("DockerSandboxProvider cancellation", () => {
  it("kills the per-agent container when command timeout closes the exec stream", async () => {
    let observedSignal: AbortSignal | undefined;
    const transport = readyTransport((_path, _body, signal) => {
      observedSignal = signal;
      return new Promise<Buffer>((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => reject(signal.reason instanceof Error ? signal.reason : new Error("aborted")),
          { once: true },
        );
      });
    });

    await expect(
      new DockerSandboxProvider(transport).execute(
        { argv: ["sh", "-c", "sleep 30"], timeoutMs: 100 },
        scope(),
      ),
    ).rejects.toThrow("Sandbox command timed out");

    expect(observedSignal?.aborted).toBe(true);
    expect(transport.request).toHaveBeenCalledWith(
      expect.stringMatching(/^\/containers\/team6-agent-[a-f0-9]{32}\/kill\?signal=KILL$/),
      undefined,
      "POST",
      expect.any(AbortSignal),
    );
  });

  it("kills the per-agent container when its caller cancels", async () => {
    const controller = new AbortController();
    const transport = readyTransport(
      (_path, _body, signal) =>
        new Promise<Buffer>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(signal.reason instanceof Error ? signal.reason : new Error("aborted")),
            { once: true },
          );
        }),
    );
    const execution = new DockerSandboxProvider(transport).execute(
      { argv: ["sh", "-c", "sleep 30"], timeoutMs: 10_000 },
      scope(controller.signal),
    );
    await vi.waitFor(() => {
      expect(transport.request).toHaveBeenCalledWith(
        expect.stringMatching(/^\/containers\/team6-agent-[a-f0-9]{32}\/exec$/),
        expect.anything(),
        "POST",
        expect.any(AbortSignal),
      );
    });
    controller.abort(new Error("Cancelled by test"));

    await expect(execution).rejects.toThrow("Cancelled by test");
    expect(transport.request).toHaveBeenCalledWith(
      expect.stringMatching(/^\/containers\/team6-agent-[a-f0-9]{32}\/kill\?signal=KILL$/),
      undefined,
      "POST",
      expect.any(AbortSignal),
    );
  });
});
