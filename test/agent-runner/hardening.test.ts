import { describe, expect, it } from "vitest";
import type { AgentScope } from "../../src/agent-protocol.js";
import { ProcessAgentRunner } from "../../src/agent-runner.js";

const scope: AgentScope = { user_id: "user-1", space_id: "space-1" };

function runnerFor(source: string) {
  return new ProcessAgentRunner({ command: process.execPath, args: ["-e", source] });
}

async function waitUntilProcessExits(pid: number, timeoutMs = 2_500): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0);
    } catch {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Process ${pid} did not exit within ${timeoutMs}ms`);
}

describe("ProcessAgentRunner hard limits", () => {
  it("enforces the deadline sent in the invoke request", async () => {
    const runner = runnerFor(`
      const readline = require('node:readline');
      readline.createInterface({ input: process.stdin }).on('line', () => {});
      setInterval(() => {}, 1000);
    `);

    await expect(
      runner.run(
        {
          requestId: "deadline-1",
          agentId: "test-agent",
          input: {},
          scope,
          deadlineAt: new Date(Date.now() + 100).toISOString(),
        },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ code: "AGENT_DEADLINE_EXCEEDED" });
  });

  it("fails closed when an agent sends an unsupported wait frame", async () => {
    const runner = runnerFor(`
      const readline = require('node:readline');
      readline.createInterface({ input: process.stdin }).on('line', (line) => {
        const message = JSON.parse(line);
        if (message.type === 'invoke') {
          process.stdout.write(JSON.stringify({
            protocol: 'agent-runner.v2', type: 'wait',
            request_id: message.request_id, wait_for: 'child:run-2', timeout_ms: 1000
          }) + '\\n');
        }
      });
    `);

    await expect(
      runner.run(
        { requestId: "wait-1", agentId: "test-agent", input: {}, scope },
        new AbortController().signal,
      ),
    ).rejects.toThrow("wait messages are not supported");
  });

  it.skipIf(process.platform === "win32")(
    "terminates descendants with the agent process group",
    async () => {
      const runner = runnerFor(`
      const { spawn } = require('node:child_process');
      const readline = require('node:readline');
      readline.createInterface({ input: process.stdin }).on('line', (line) => {
        const message = JSON.parse(line);
        if (message.type !== 'invoke') return;
        const descendant = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
          stdio: "ignore",
        });
        process.stdout.write(JSON.stringify({
          protocol: 'agent-runner.v2', type: 'result', request_id: message.request_id,
          ok: true, output: { pid: descendant.pid }
        }) + '\\n');
      });
      `);

      const output = await runner.run(
        { requestId: "tree-1", agentId: "test-agent", input: {}, scope },
        new AbortController().signal,
      );
      expect(output).toMatchObject({ pid: expect.any(Number) });
      const descendantPid = (output as { pid: number }).pid;
      try {
        await waitUntilProcessExits(descendantPid);
      } catch (error) {
        try {
          process.kill(descendantPid, "SIGKILL");
        } catch {
          // It exited during cleanup.
        }
        throw error;
      }
    },
  );
});
