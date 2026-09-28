import { beforeEach, describe, expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import {
  type AgentCapability,
  type AgentHandler,
  type DelegationRequest,
  InMemoryCollaborationPort,
} from "../../src/ports/collaboration-port.js";
import { testScope } from "../helpers/scope.js";

describe("CollaborationPort", () => {
  let port: InMemoryCollaborationPort;
  let sampleScope: AgentScope;

  beforeEach(() => {
    port = new InMemoryCollaborationPort();
    sampleScope = testScope({ actorId: "actor-1" });
  });

  describe("Agent Registration", () => {
    it("should register an agent", () => {
      const capability: AgentCapability = {
        agentId: "agent-1",
        name: "Test Agent",
        description: "A test agent",
        capabilities: ["test"],
      };

      const handler: AgentHandler = {
        execute: async (_input: unknown) => ({ result: "test" }),
      };

      port.registerAgent(capability, handler);

      // Verify by discovering
      const discovered = port.discover();
      expect(discovered).resolves.toHaveLength(1);
    });

    it("should unregister an agent", async () => {
      const capability: AgentCapability = {
        agentId: "agent-1",
        name: "Test Agent",
        description: "A test agent",
        capabilities: ["test"],
      };

      const handler: AgentHandler = {
        execute: async (_input: unknown) => ({ result: "test" }),
      };

      port.registerAgent(capability, handler);
      port.unregisterAgent("agent-1");

      const discovered = await port.discover();
      expect(discovered).toHaveLength(0);
    });
  });

  describe("Discovery", () => {
    beforeEach(() => {
      // Register multiple agents
      port.registerAgent(
        {
          agentId: "analyzer",
          name: "Code Analyzer",
          description: "Analyzes code quality",
          capabilities: ["analysis", "code-review"],
          costEstimate: { minUsd: 0.01, maxUsd: 0.1 },
          durationEstimate: { minMs: 1000, maxMs: 5000 },
        },
        {
          execute: async (_input: unknown) => ({ analysis: "good" }),
        },
      );

      port.registerAgent(
        {
          agentId: "formatter",
          name: "Code Formatter",
          description: "Formats code",
          capabilities: ["formatting"],
          costEstimate: { minUsd: 0.001, maxUsd: 0.01 },
          durationEstimate: { minMs: 100, maxMs: 1000 },
        },
        {
          execute: async (_input: unknown) => ({ formatted: true }),
        },
      );

      port.registerAgent(
        {
          agentId: "tester",
          name: "Test Generator",
          description: "Generates tests",
          capabilities: ["testing", "code-review"],
          costEstimate: { minUsd: 0.05, maxUsd: 0.5 },
          durationEstimate: { minMs: 2000, maxMs: 10000 },
        },
        {
          execute: async (_input: unknown) => ({ tests: [] }),
        },
      );
    });

    it("should discover all agents without filter", async () => {
      const agents = await port.discover();
      expect(agents).toHaveLength(3);
    });

    it("should filter by capability", async () => {
      const agents = await port.discover({
        capabilities: ["code-review"],
      });

      expect(agents).toHaveLength(2);
      expect(agents.map((a) => a.agentId).sort()).toEqual(["analyzer", "tester"]);
    });

    it("should filter by name pattern", async () => {
      const agents = await port.discover({
        namePattern: "Code",
      });

      expect(agents).toHaveLength(2);
      expect(agents.map((a) => a.agentId).sort()).toEqual(["analyzer", "formatter"]);
    });

    it("should filter by max cost", async () => {
      const agents = await port.discover({
        maxCostUsd: 0.02,
      });

      expect(agents).toHaveLength(2);
      expect(agents.map((a) => a.agentId).sort()).toEqual(["analyzer", "formatter"]);
    });

    it("should filter by max duration", async () => {
      const agents = await port.discover({
        maxDurationMs: 1500,
      });

      expect(agents).toHaveLength(2);
      expect(agents.map((a) => a.agentId).sort()).toEqual(["analyzer", "formatter"]);
    });

    it("should apply multiple filters", async () => {
      const agents = await port.discover({
        capabilities: ["code-review"],
        maxCostUsd: 0.05,
      });

      expect(agents).toHaveLength(1);
      expect(agents[0].agentId).toBe("analyzer");
    });
  });

  describe("Synchronous Invocation", () => {
    it("should invoke an agent and return result", async () => {
      const handler: AgentHandler = {
        execute: async (input: unknown) => {
          return { result: `processed: ${JSON.stringify(input)}` };
        },
      };

      port.registerAgent(
        {
          agentId: "processor",
          name: "Processor",
          description: "Processes input",
          capabilities: ["processing"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "processor",
        scope: sampleScope,
        input: { data: "test" },
      };

      const result = await port.invoke(request);

      expect(result.status).toBe("completed");
      expect(result.requestId).toBe("req-1");
      expect(result.output).toEqual({ result: 'processed: {"data":"test"}' });
      expect(result.usage?.durationMs).toBeGreaterThan(0);
    });

    it("should handle agent not found", async () => {
      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "nonexistent",
        scope: sampleScope,
        input: {},
      };

      const result = await port.invoke(request);

      expect(result.status).toBe("failed");
      expect(result.error?.code).toBe("agent_not_found");
      expect(result.error?.retryable).toBe(false);
    });

    it("should handle execution error", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          throw new Error("Execution failed");
        },
      };

      port.registerAgent(
        {
          agentId: "failing",
          name: "Failing Agent",
          description: "Always fails",
          capabilities: ["failing"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "failing",
        scope: sampleScope,
        input: {},
      };

      const result = await port.invoke(request);

      expect(result.status).toBe("failed");
      expect(result.error?.code).toBe("execution_error");
      expect(result.error?.message).toBe("Execution failed");
      expect(result.error?.retryable).toBe(true);
    });

    it("should handle timeout", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 200));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "slow",
          name: "Slow Agent",
          description: "Takes time",
          capabilities: ["slow"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "slow",
        scope: sampleScope,
        input: {},
        timeout: 100,
      };

      const result = await port.invoke(request);

      expect(result.status).toBe("failed");
      expect(result.error?.message).toContain("timeout");
    });
  });

  describe("Asynchronous Invocation", () => {
    it("should invoke agent asynchronously", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 50));
          return { result: "async done" };
        },
      };

      port.registerAgent(
        {
          agentId: "async",
          name: "Async Agent",
          description: "Async execution",
          capabilities: ["async"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "async",
        scope: sampleScope,
        input: {},
      };

      const handle = await port.invokeAsync(request);

      expect(handle.requestId).toBe("req-1");
      expect(handle.childRunId).toBe("child-req-1");

      // Initially no result
      const polled = await handle.poll();
      expect(polled).toBeNull();

      // Wait for completion
      const result = await handle.wait(5000);
      expect(result.status).toBe("completed");
      expect(result.output).toEqual({ result: "async done" });
    });

    it("should handle async agent not found", async () => {
      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "nonexistent",
        scope: sampleScope,
        input: {},
      };

      const handle = await port.invokeAsync(request);

      const result = await handle.poll();
      expect(result).not.toBeNull();
      expect(result!.status).toBe("failed");
      expect(result!.error?.code).toBe("agent_not_found");
    });

    it("should poll for result", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 100));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "poller",
          name: "Poller",
          description: "For polling",
          capabilities: ["polling"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "poller",
        scope: sampleScope,
        input: {},
      };

      const handle = await port.invokeAsync(request);

      // Poll immediately - should be null
      let result = await handle.poll();
      expect(result).toBeNull();

      // Wait and poll again
      await new Promise((resolve) => setTimeout(resolve, 150));
      result = await handle.poll();
      expect(result).not.toBeNull();
      expect(result!.status).toBe("completed");
    });

    it("should timeout when waiting", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "long",
          name: "Long Running",
          description: "Takes long time",
          capabilities: ["long"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "long",
        scope: sampleScope,
        input: {},
      };

      const handle = await port.invokeAsync(request);
      const result = await handle.wait(100);

      expect(result.status).toBe("timeout");
      expect(result.error?.code).toBe("wait_timeout");
    });

    it("should cancel async invocation", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "cancellable",
          name: "Cancellable",
          description: "Can be cancelled",
          capabilities: ["cancel"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "cancellable",
        scope: sampleScope,
        input: {},
      };

      const handle = await port.invokeAsync(request);

      // Cancel immediately
      const cancelled = await handle.cancel();
      expect(cancelled).toBe(true);

      // Check status
      const status = await port.getStatus("req-1");
      expect(status?.status).toBe("cancelled");
    });
  });

  describe("Status and Cancellation", () => {
    it("should get delegation status", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => ({ result: "test" }),
      };

      port.registerAgent(
        {
          agentId: "agent",
          name: "Agent",
          description: "Test agent",
          capabilities: ["test"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "agent",
        scope: sampleScope,
        input: {},
      };

      await port.invoke(request);

      const status = await port.getStatus("req-1");
      expect(status).not.toBeNull();
      expect(status!.status).toBe("completed");
      expect(status!.requestId).toBe("req-1");
    });

    it("should return null for unknown request", async () => {
      const status = await port.getStatus("nonexistent");
      expect(status).toBeNull();
    });

    it("should cancel delegation", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "agent",
          name: "Agent",
          description: "Test agent",
          capabilities: ["test"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "agent",
        scope: sampleScope,
        input: {},
      };

      await port.invokeAsync(request);

      const cancelled = await port.cancel("req-1");
      expect(cancelled).toBe(true);

      const status = await port.getStatus("req-1");
      expect(status?.status).toBe("cancelled");
    });

    it("should not cancel completed delegation", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => ({ result: "done" }),
      };

      port.registerAgent(
        {
          agentId: "agent",
          name: "Agent",
          description: "Test agent",
          capabilities: ["test"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "agent",
        scope: sampleScope,
        input: {},
      };

      await port.invoke(request);

      const cancelled = await port.cancel("req-1");
      expect(cancelled).toBe(false);

      const status = await port.getStatus("req-1");
      expect(status?.status).toBe("completed");
    });

    it("should not cancel nonexistent delegation", async () => {
      const cancelled = await port.cancel("nonexistent");
      expect(cancelled).toBe(false);
    });
  });

  describe("Wait for Completion", () => {
    it("should wait for async completion", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 100));
          return { result: "waited" };
        },
      };

      port.registerAgent(
        {
          agentId: "waiter",
          name: "Waiter",
          description: "For waiting",
          capabilities: ["wait"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "waiter",
        scope: sampleScope,
        input: {},
      };

      await port.invokeAsync(request);

      const result = await port.wait("req-1", 5000);
      expect(result.status).toBe("completed");
      expect(result.output).toEqual({ result: "waited" });
    });

    it("should timeout when waiting too long", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          return { result: "done" };
        },
      };

      port.registerAgent(
        {
          agentId: "slow",
          name: "Slow",
          description: "Slow agent",
          capabilities: ["slow"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "slow",
        scope: sampleScope,
        input: {},
      };

      await port.invokeAsync(request);

      const result = await port.wait("req-1", 100);
      expect(result.status).toBe("timeout");
      expect(result.error?.code).toBe("wait_timeout");
    });
  });

  describe("Trace and Metadata", () => {
    it("should pass trace information", async () => {
      let receivedInput: any;

      const handler: AgentHandler = {
        execute: async (input: unknown) => {
          receivedInput = input;
          return { result: "traced" };
        },
      };

      port.registerAgent(
        {
          agentId: "tracer",
          name: "Tracer",
          description: "Traces requests",
          capabilities: ["tracing"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "tracer",
        scope: sampleScope,
        input: { data: "test" },
        traceId: "trace-123",
        parentSpanId: "span-456",
        metadata: { source: "test" },
      };

      await port.invoke(request);

      expect(receivedInput).toEqual({ data: "test" });
    });

    it("should handle priority", async () => {
      const handler: AgentHandler = {
        execute: async (_input: unknown) => ({ result: "prioritized" }),
      };

      port.registerAgent(
        {
          agentId: "prioritizer",
          name: "Prioritizer",
          description: "Handles priority",
          capabilities: ["priority"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "prioritizer",
        scope: sampleScope,
        input: {},
        priority: "high",
      };

      const result = await port.invoke(request);
      expect(result.status).toBe("completed");
    });
  });
});
