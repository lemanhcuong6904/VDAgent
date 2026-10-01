import { describe, expect, it, vi } from "vitest";
import type { AgentScope } from "../../src/agent-protocol.js";
import { ProcessAgentRunner } from "../../src/agent-runner.js";

describe("M9.3: Agent Runner v2 - Authorization", () => {
  const mockScope: AgentScope = {
    user_id: "user-1",
    space_id: "space-1",
  };

  it("should authorize allowed port calls", async () => {
    const onPortCall = vi.fn().mockResolvedValue({ success: true });
    const authorizationCheck = vi.fn().mockResolvedValue(true);

    const runner = new ProcessAgentRunner({
      command: "node",
      args: [
        "-e",
        `
        process.stdin.on('data', (chunk) => {
          const msg = JSON.parse(chunk.toString());
          if (msg.type === 'invoke') {
            const portCall = {
              protocol: 'agent-runner.v2',
              type: 'port_call',
              request_id: msg.request_id,
              call_id: 'call-1',
              port: 'tools',
              operation: 'echo',
              input: { message: 'test' },
              sequence: 1
            };
            process.stdout.write(JSON.stringify(portCall) + '\\n');
          }
          if (msg.type === 'port_result' && msg.ok) {
            const result = {
              protocol: 'agent-runner.v2',
              type: 'result',
              request_id: msg.request_id,
              ok: true,
              output: { done: true }
            };
            process.stdout.write(JSON.stringify(result) + '\\n');
          }
        });
      `,
      ],
      onPortCall,
      authorizationCheck,
    });

    const controller = new AbortController();
    const resultPromise = runner.run(
      {
        requestId: "req-1",
        agentId: "test-agent",
        input: { task: "echo test" },
        scope: mockScope,
      },
      controller.signal,
    );

    const result = await resultPromise;

    expect(authorizationCheck).toHaveBeenCalledWith("tools", "echo");
    expect(onPortCall).toHaveBeenCalled();
    expect(result).toEqual({ done: true });
  });

  it("should block unauthorized port calls", async () => {
    const onPortCall = vi.fn();
    const authorizationCheck = vi.fn().mockResolvedValue(false);

    const runner = new ProcessAgentRunner({
      command: "node",
      args: [
        "-e",
        `
        process.stdin.on('data', (chunk) => {
          const msg = JSON.parse(chunk.toString());
          if (msg.type === 'invoke') {
            const portCall = {
              protocol: 'agent-runner.v2',
              type: 'port_call',
              request_id: msg.request_id,
              call_id: 'call-1',
              port: 'tools',
              operation: 'delete_all',
              sequence: 1
            };
            process.stdout.write(JSON.stringify(portCall) + '\\n');
          }
          if (msg.type === 'port_result' && !msg.ok && msg.error?.code === 'unauthorized') {
            const result = {
              protocol: 'agent-runner.v2',
              type: 'result',
              request_id: msg.request_id,
              ok: false,
              error: { code: 'unauthorized', message: 'Port call denied' }
            };
            process.stdout.write(JSON.stringify(result) + '\\n');
          }
        });
      `,
      ],
      onPortCall,
      authorizationCheck,
    });

    const controller = new AbortController();
    const resultPromise = runner.run(
      {
        requestId: "req-2",
        agentId: "test-agent",
        input: {},
        scope: mockScope,
      },
      controller.signal,
    );

    await expect(resultPromise).rejects.toThrow();
    expect(authorizationCheck).toHaveBeenCalledWith("tools", "delete_all");
    expect(onPortCall).not.toHaveBeenCalled();
  });
});

describe("M9.3: Agent Runner v2 - Sequence Validation", () => {
  const mockScope: AgentScope = {
    user_id: "user-1",
    space_id: "space-1",
  };

  it("should accept monotonically increasing sequence numbers", async () => {
    const onPortCall = vi
      .fn()
      .mockResolvedValueOnce({ result: "first" })
      .mockResolvedValueOnce({ result: "second" });

    const runner = new ProcessAgentRunner({
      command: "node",
      args: [
        "-e",
        `
        let callCount = 0;
        process.stdin.on('data', (chunk) => {
          const msg = JSON.parse(chunk.toString());
          if (msg.type === 'invoke') {
            // Send first port call
            const call1 = {
              protocol: 'agent-runner.v2',
              type: 'port_call',
              request_id: msg.request_id,
              call_id: 'call-1',
              port: 'tools',
              operation: 'first',
              sequence: 1
            };
            process.stdout.write(JSON.stringify(call1) + '\\n');
          }
          if (msg.type === 'port_result' && msg.call_id === 'call-1' && msg.ok) {
            // Send second port call
            const call2 = {
              protocol: 'agent-runner.v2',
              type: 'port_call',
              request_id: msg.request_id,
              call_id: 'call-2',
              port: 'tools',
              operation: 'second',
              sequence: 2
            };
            process.stdout.write(JSON.stringify(call2) + '\\n');
          }
          if (msg.type === 'port_result' && msg.call_id === 'call-2' && msg.ok) {
            const result = {
              protocol: 'agent-runner.v2',
              type: 'result',
              request_id: msg.request_id,
              ok: true,
              output: { done: true }
            };
            process.stdout.write(JSON.stringify(result) + '\\n');
          }
        });
      `,
      ],
      onPortCall,
    });

    const controller = new AbortController();
    const result = await runner.run(
      {
        requestId: "req-3",
        agentId: "test-agent",
        input: {},
        scope: mockScope,
      },
      controller.signal,
    );

    expect(onPortCall).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ done: true });
  });
});

describe("M9.3: Agent Runner v2 - Idempotency", () => {
  const mockScope: AgentScope = {
    user_id: "user-1",
    space_id: "space-1",
  };

  it("should pass idempotency key to port handler", async () => {
    const onPortCall = vi.fn().mockResolvedValue({ created: true });

    const runner = new ProcessAgentRunner({
      command: "node",
      args: [
        "-e",
        `
        process.stdin.on('data', (chunk) => {
          const msg = JSON.parse(chunk.toString());
          if (msg.type === 'invoke') {
            const portCall = {
              protocol: 'agent-runner.v2',
              type: 'port_call',
              request_id: msg.request_id,
              call_id: 'call-1',
              port: 'warehouse',
              operation: 'create_table',
              input: { name: 'users' },
              sequence: 1,
              idempotency_key: 'create-users-table-20230927'
            };
            process.stdout.write(JSON.stringify(portCall) + '\\n');
          }
          if (msg.type === 'port_result' && msg.ok) {
            const result = {
              protocol: 'agent-runner.v2',
              type: 'result',
              request_id: msg.request_id,
              ok: true,
              output: { done: true }
            };
            process.stdout.write(JSON.stringify(result) + '\\n');
          }
        });
      `,
      ],
      onPortCall,
    });

    const controller = new AbortController();
    await runner.run(
      {
        requestId: "req-5",
        agentId: "test-agent",
        input: {},
        scope: mockScope,
      },
      controller.signal,
    );

    expect(onPortCall).toHaveBeenCalledWith(
      expect.objectContaining({
        port: "warehouse",
        operation: "create_table",
        idempotencyKey: "create-users-table-20230927",
      }),
    );
  });
});

describe("M9.3: Agent Runner v2 - Environment Safety", () => {
  it("should filter environment variables", async () => {
    const runner = new ProcessAgentRunner({
      command: "node",
      args: [
        "-e",
        `
        const hasDbPassword = 'DB_PASSWORD' in process.env;
        const hasPath = 'PATH' in process.env;
        process.stdin.on('data', (chunk) => {
          const msg = JSON.parse(chunk.toString());
          if (msg.type === 'invoke') {
            const result = {
              protocol: 'agent-runner.v2',
              type: 'result',
              request_id: msg.request_id,
              ok: true,
              output: { hasDbPassword, hasPath }
            };
            process.stdout.write(JSON.stringify(result) + '\\n');
          }
        });
      `,
      ],
      env: {
        PATH: "/usr/bin",
        DB_PASSWORD: "secret123",
        API_KEY: "key456",
      },
    });

    const controller = new AbortController();
    const result = await runner.run(
      {
        requestId: "req-6",
        agentId: "test-agent",
        input: {},
        scope: {
          user_id: "user-1",
          space_id: "space-1",
        },
      },
      controller.signal,
    );

    expect(result).toEqual({
      hasDbPassword: false,
      hasPath: true,
    });
  });
});
