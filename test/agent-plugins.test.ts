import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import type { AgentRuntime } from "../src/agent-contract.js";
import { createPythonRoster } from "./support/python-roster.js";

const ARTIFACT = /\b(?:ds|ch|rp)_[a-zA-Z0-9]{12}\b/g;

/** Answers by agent and requested shape; JSON calls get schema-valid choices. */
function fakeRuntime(calls: Array<{ agentId: string; json: boolean }>): AgentRuntime {
  return {
    async prompt(input: { agentId: string; system: string; prompt: string }) {
      const json = input.system.includes("JSON Schema");
      calls.push({ agentId: input.agentId, json });
      if (input.agentId === "orchestrator" && json) {
        if (/Task:\nhello/i.test(input.prompt))
          return JSON.stringify({ answer: "Hi there.", steps: [] });
        return JSON.stringify({
          answer: "",
          steps: [
            "warehouse.query",
            "dataset.compare",
            "dataset.insight",
            "dataset.visualize",
            "dataset.report",
          ],
        });
      }
      if (input.agentId === "visualize" && json) {
        return JSON.stringify({
          kind: "line",
          x: "month",
          y: "revenue",
          title: "Revenue by month",
        });
      }
      if (input.agentId === "orchestrator") {
        const cited = [...new Set(input.prompt.match(ARTIFACT) ?? [])];
        return `Revenue analysis complete. Artifacts: ${cited.join(", ")}. It might be seasonal.`;
      }
      return `${input.agentId} summary for the supplied evidence.`;
    },
  } as unknown as AgentRuntime;
}

describe("Python reference roster", () => {
  it("keeps agents/manifests in sync with the Python agent classes", () => {
    expect(() =>
      execFileSync(
        "uv",
        ["run", "--no-sync", "--project", "agents", "python", "agents/gen_manifests.py", "--check"],
        { stdio: "pipe" },
      ),
    ).not.toThrow();
  });

  it("registers the six product agents with the same ids and only the orchestrator delegates", async () => {
    const { agents } = await createPythonRoster(fakeRuntime([]));
    expect(agents.list().map(({ id }) => id)).toEqual([
      "orchestrator",
      "data",
      "compare",
      "insight",
      "visualize",
      "report",
    ]);
    expect(agents.delegatable().map(({ descriptor }) => descriptor.id)).not.toContain(
      "orchestrator",
    );
    expect(agents.get("orchestrator")?.descriptor.tools).toContain("agents.delegate");
  });

  it("runs the full workflow and cites only artifacts that were persisted", async () => {
    const calls: Array<{ agentId: string; json: boolean }> = [];
    const roster = await createPythonRoster(fakeRuntime(calls));
    const answer = await roster.ask(
      "Analyze monthly_sales, compare January and February, explain the trend, and create a chart report.",
    );

    expect(roster.invocations.map(({ agent, status }) => [agent, status])).toEqual([
      ["data", "completed"],
      ["compare", "completed"],
      ["insight", "completed"],
      ["visualize", "completed"],
      ["report", "completed"],
    ]);
    const [dataset] = [...roster.artifacts.datasets.values()];
    const [chart] = [...roster.artifacts.charts.values()];
    const [report] = [...roster.artifacts.reports.values()];
    expect(dataset?.name).toBe("monthly_sales");
    expect(chart).toMatchObject({ datasetId: dataset?.id, title: "Revenue by month" });
    expect(report?.markdown).toContain("## Comparison");
    expect(report?.markdown).toContain(`{{chart:${chart?.id}}}`);

    for (const id of [dataset?.id, chart?.id, report?.id]) expect(answer).toContain(id);
    // Hedges are stripped from the final answer and every model call went through the host.
    expect(answer).not.toMatch(/might/);
    expect(new Set(calls.map(({ agentId }) => agentId))).toEqual(
      new Set(["orchestrator", "data", "compare", "insight", "visualize", "report"]),
    );
  }, 60_000);

  it("answers small talk directly without delegating", async () => {
    const roster = await createPythonRoster(fakeRuntime([]));
    expect(await roster.ask("hello")).toBe("Hi there.");
    expect(roster.invocations).toEqual([]);
  }, 30_000);

  it("falls back to deterministic output when the model is unavailable", async () => {
    const failing = {
      async prompt() {
        throw new Error("model offline");
      },
    } as unknown as AgentRuntime;
    const roster = await createPythonRoster(failing);
    const answer = await roster.ask("Analyze monthly_sales and create a chart report.");
    expect(roster.invocations.map(({ agent }) => agent)).toEqual([
      "data",
      "insight",
      "visualize",
      "report",
    ]);
    expect(roster.invocations.every(({ status }) => status === "completed")).toBe(true);
    expect(roster.artifacts.reports.size).toBe(1);
    expect(answer).toMatch(/rp_[a-zA-Z0-9]{12}/);
  }, 60_000);
});
