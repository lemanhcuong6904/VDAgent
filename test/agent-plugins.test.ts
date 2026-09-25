import { describe, expect, it } from "vitest";
import type { AgentContext } from "../src/agent-contract.js";
import { loadAgentPool } from "../src/registry.js";
import type { McpPoolTool } from "../src/tool-pool.js";

describe("built-in analytics agents", () => {
  it("registers all six product agents", async () => {
    const agents = await loadAgentPool(["src/agents/index.ts"]);

    expect(agents.list().map(({ id }) => id)).toEqual([
      "orchestrator",
      "data",
      "compare",
      "insight",
      "visualize",
      "report",
    ]);
    expect(agents.get("orchestrator")?.descriptor.tools).toContain("agents.delegate");
    expect(agents.get("data")?.descriptor.tools).toContain("warehouse.run_query");
    expect(agents.get("compare")?.descriptor.tools).toContain("warehouse.describe_dataset");
    expect(agents.get("insight")?.descriptor.tools).toContain("warehouse.get_dataset_rows");
    expect(agents.get("visualize")?.descriptor.tools).toContain("warehouse.create_chart");
  });

  it("preflights a named table and passes its persisted dataset ID to Pi", async () => {
    const agents = await loadAgentPool(["src/agents/index.ts"]);
    const agent = agents.get("data");
    expect(agent).toBeDefined();
    const calledTools: string[] = [];
    let runtimePrompt = "";
    const context = {
      userId: "user-1",
      spaceId: "space-1",
      sessionId: "session-1",
      runId: "run-1",
      taskId: "task-1",
      signal: new AbortController().signal,
      tools: agent?.descriptor.tools.map((name) => ({ name }) as McpPoolTool) ?? [],
      pool: {
        async call(name: string) {
          calledTools.push(name);
          if (name === "warehouse.list_sources") {
            return { warehouses: [{ id: "sales", name: "Sales" }] };
          }
          if (name === "warehouse.list_tables") {
            return { tables: [{ name: "monthly_sales", rowCount: 4 }] };
          }
          if (name === "warehouse.describe_table") {
            return { table: { name: "monthly_sales" } };
          }
          if (name === "warehouse.run_query") {
            return { dataset_id: "ds_real_123", row_count: 4 };
          }
          throw new Error(`Unexpected tool ${name}`);
        },
      },
      runtime: {
        async prompt(input: { prompt: string }) {
          runtimePrompt = input.prompt;
          return "Dataset ds_real_123";
        },
      },
    } as unknown as AgentContext;

    await agent?.run({ prompt: "Query monthly_sales" }, context);

    expect(calledTools).toEqual([
      "warehouse.list_sources",
      "warehouse.list_tables",
      "warehouse.describe_table",
      "warehouse.run_query",
    ]);
    expect(runtimePrompt).toContain('"dataset_id":"ds_real_123"');
    expect(runtimePrompt).not.toContain('"dataset_id":"monthly_sales"');
  });

  it("does not pass a table name as a dataset ID when persistence fails", async () => {
    const agents = await loadAgentPool(["src/agents/index.ts"]);
    const agent = agents.get("data");
    let runtimePrompt = "";
    const context = {
      userId: "user-1",
      spaceId: "space-1",
      sessionId: "session-1",
      runId: "run-1",
      taskId: "task-1",
      signal: new AbortController().signal,
      tools: agent?.descriptor.tools.map((name) => ({ name }) as McpPoolTool) ?? [],
      pool: {
        async call(name: string) {
          if (name === "warehouse.list_sources")
            return { warehouses: [{ id: "sales", name: "Sales" }] };
          if (name === "warehouse.list_tables")
            return { tables: [{ name: "monthly_sales", rowCount: 4 }] };
          if (name === "warehouse.describe_table") return { table: { name: "monthly_sales" } };
          if (name === "warehouse.run_query") return { name: "monthly_sales", row_count: 4 };
          throw new Error(`Unexpected tool ${name}`);
        },
      },
      runtime: {
        async prompt(input: { prompt: string }) {
          runtimePrompt = input.prompt;
          return "No persisted dataset";
        },
      },
    } as unknown as AgentContext;

    await agent?.run({ prompt: "Query monthly_sales" }, context);

    expect(runtimePrompt).toContain("Warehouse query did not return a persisted dataset ID");
    expect(runtimePrompt).not.toContain('"dataset_id":"monthly_sales"');
  });

  it("runs requested specialists in order and gives the final Pi turn evidence only", async () => {
    const agents = await loadAgentPool(["src/agents/index.ts"]);
    const agent = agents.get("orchestrator");
    expect(agent).toBeDefined();
    const delegated: string[] = [];
    let finalPrompt = "";
    let finalTools: readonly string[] = ["unexpected"];
    const context = {
      userId: "user-1",
      spaceId: "space-1",
      sessionId: "session-1",
      runId: "run-1",
      taskId: "task-1",
      depth: 0,
      signal: new AbortController().signal,
      tools: agent?.descriptor.tools.map((name) => ({ name }) as McpPoolTool) ?? [],
      pool: {
        async call(_name: string, input: { agent: string; message: string }) {
          delegated.push(input.agent);
          return input.agent === "data"
            ? "monthly_sales dataset ds_123456789abc"
            : input.agent === "visualize"
              ? "Created chart ch_123456abcdef"
              : input.agent === "report"
                ? "Saved report rp_abcdef123456 with chart ch_123456abcdef"
                : `${input.agent} result for ds_123456789abc`;
        },
      },
      runtime: {
        async prompt(input: { prompt: string; tools: readonly string[] }) {
          finalPrompt = input.prompt;
          finalTools = input.tools;
          return (
            "North +$25. The South drop suggests competition.\n\n" +
            "![chart](sandbox:ch_123456abcdef) " +
            "[report](report:rp_abcdef123456) ds_ffffffffffff"
          );
        },
      },
    } as unknown as AgentContext;

    const answer = await agent?.run(
      {
        prompt:
          "Analyze monthly_sales, compare January and February, explain the drivers, and save a chart report.",
      },
      context,
    );

    expect(delegated).toEqual(["data", "compare", "insight", "visualize", "report"]);
    expect(finalPrompt).toContain("ds_123456789abc");
    expect(finalPrompt).toContain("[visualize]");
    expect(finalTools).toEqual([]);
    expect(answer).toContain("rp_abcdef123456");
    expect(answer).toContain("ch_123456abcdef");
    expect(answer).toContain("unverified artifact");
    expect(answer).not.toContain("ds_ffffffffffff");
    expect(answer).not.toContain("suggests");
    expect(answer).not.toContain("sandbox:");
    expect(answer).not.toContain("report:");
    expect(answer).toContain("ds_123456789abc");
  });

  it("persists a concise fallback report when Pi cannot finish the Report turn", async () => {
    const agents = await loadAgentPool(["src/agents/index.ts"]);
    const agent = agents.get("report");
    expect(agent).toBeDefined();
    const calledTools: string[] = [];
    const context = {
      userId: "user-1",
      spaceId: "space-1",
      sessionId: "session-1",
      runId: "run-1",
      taskId: "task-1",
      depth: 1,
      signal: new AbortController().signal,
      tools: agent?.descriptor.tools.map((name) => ({ name }) as McpPoolTool) ?? [],
      pool: {
        async call(name: string) {
          calledTools.push(name);
          if (name === "warehouse.describe_dataset") {
            return {
              name: "monthly_sales",
              columns: [
                { name: "month", type: "date" },
                { name: "revenue", type: "number" },
              ],
            };
          }
          if (name === "warehouse.get_dataset_rows") {
            return { rows: [{ month: "2025-01", revenue: 120 }] };
          }
          if (name === "warehouse.create_chart") return { id: "ch_123456abcdef" };
          if (name === "warehouse.save_report") return { id: "rp_abcdef123456" };
          throw new Error(`Unexpected tool ${name}`);
        },
      },
      runtime: {
        async prompt() {
          throw new Error("Pi returned no assistant message");
        },
      },
    } as unknown as AgentContext;

    const result = await agent?.run(
      {
        prompt:
          "Create a report from dataset ds_123456789abc.\n\n[compare]\nRevenue increased.\n\n[insight]\nNorth increased.\n\n[visualize]\nCreated chart ch_123456abcdef.",
      },
      context,
    );

    expect(calledTools).toEqual([
      "warehouse.describe_dataset",
      "warehouse.get_dataset_rows",
      "warehouse.save_report",
    ]);
    expect(result).toContain("rp_abcdef123456");
    expect(result).toContain("ch_123456abcdef");
    expect(result).toContain("ds_123456789abc");
  });
});
