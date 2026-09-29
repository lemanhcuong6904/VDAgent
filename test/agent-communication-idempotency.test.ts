import { Type } from "typebox";
import { describe, expect, it, vi } from "vitest";
import type { AgentPlugin } from "../src/agent-contract.js";
import { AgentPool } from "../src/registry.js";
import type { McpPoolTool, ToolScope } from "../src/tool-pool.js";
import { createAgentCommunicationTools } from "../src/tools/agent-communication.js";

function plugin(id: string): AgentPlugin {
  return {
    descriptor: {
      id,
      version: "1.0.0",
      name: id,
      description: id,
      acceptsDelegation: true,
      input: Type.Object({ prompt: Type.String() }),
      tools: ["agents.ask"],
    },
    async run() {
      return "ok";
    },
  };
}

function askHarness() {
  type AskRow = {
    id: string;
    task_id: string;
    user_id: string;
    space_id: string;
    question_id: string;
    from_agent: string;
    to_agent: string;
    content: unknown;
    status: string;
    answer: unknown;
    answer_status: string | null;
  };
  const asks = new Map<string, AskRow>();
  const query = async <Row = unknown>(text: string, values: unknown[] = []) => {
    let rows: unknown[] = [];
    if (text.includes("SELECT id, task_id, user_id, space_id, question_id")) {
      const row = asks.get(`${String(values[0])}:${String(values[1])}`);
      rows = row ? [structuredClone(row)] : [];
    } else if (text.includes("FROM web_wait_for_edges WHERE task_id")) {
      rows = [];
    } else if (text.includes("INSERT INTO web_agent_asks")) {
      const row: AskRow = {
        id: String(values[0]),
        task_id: String(values[1]),
        user_id: String(values[2]),
        space_id: String(values[3]),
        question_id: String(values[4]),
        from_agent: String(values[5]),
        to_agent: String(values[6]),
        content: JSON.parse(String(values[7])),
        status: "pending",
        answer: null,
        answer_status: null,
      };
      asks.set(`${row.task_id}:${row.question_id}`, row);
    } else if (text.includes("SELECT status, answer, answer_status FROM web_agent_asks")) {
      const row = asks.get(`${String(values[0])}:${String(values[1])}`);
      rows = row ? [structuredClone(row)] : [];
    }
    return { rows: rows as Row[] };
  };
  const client = { query, release: vi.fn() };
  const database = {
    connect: async () => client,
    query,
  };
  const registry = new AgentPool();
  registry.register(plugin("sender"));
  registry.register(plugin("other-sender"));
  registry.register(plugin("receiver"));
  registry.register(plugin("other-receiver"));
  const askTool = createAgentCommunicationTools({
    database: database as never,
    runLedger: {} as never,
    pluginRegistry: registry,
  }).find(({ name }) => name === "agents.ask") as McpPoolTool;
  return { askTool, asks };
}

function scope(agentId = "sender"): ToolScope {
  return {
    userId: "user-1",
    spaceId: "space-1",
    taskId: "task-1",
    runId: `run-${agentId}`,
    agentId,
    signal: new AbortController().signal,
  };
}

describe("agents.ask idempotency", () => {
  it.each([
    ["sender", { agent: "receiver", question: "first question" }, scope("sender")],
    ["target", { agent: "other-receiver", question: "first question" }, scope("sender")],
    ["question", { agent: "receiver", question: "different question" }, scope("sender")],
  ] as const)(
    "rejects questionId reuse with a different %s",
    async (_field, changed, changedScope) => {
      const { askTool, asks } = askHarness();
      const originalScope = scope("sender");
      const initialInput = {
        agent: "receiver",
        question: "first question",
        questionId: "stable-question-id",
        timeoutMs: 0,
      };
      const first = await askTool.execute(initialInput, originalScope);
      expect(first).toMatchObject({ questionId: "stable-question-id", status: "timeout" });
      expect(asks.size).toBe(1);

      const replayScope = _field === "sender" ? scope("other-sender") : changedScope;
      await expect(
        askTool.execute(
          { ...initialInput, ...changed, questionId: "stable-question-id", timeoutMs: 0 },
          replayScope,
        ),
      ).rejects.toThrow("question_id_conflict");
      expect(asks.size).toBe(1);
    },
  );

  it("replays an identical pending question without inserting a second ask", async () => {
    const { askTool, asks } = askHarness();
    const input = {
      agent: "receiver",
      question: "same question",
      questionId: "same-question-id",
      timeoutMs: 0,
    };
    await askTool.execute(input, scope());
    const replay = await askTool.execute(input, scope());

    expect(replay).toMatchObject({ questionId: "same-question-id", status: "timeout" });
    expect(asks.size).toBe(1);
  });
});
