import { randomUUID } from "node:crypto";
import { Hono } from "hono";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrateDatabase } from "../src/database.js";
import { DEFAULT_AGENT_MANIFESTS } from "../src/platform-services.js";
import { AgentPool, loadExternalAgentPlugins } from "../src/registry.js";
import { loadToolPool } from "../src/tool-pool.js";
import { createAgentCatalogTool } from "../src/tools/agent-catalog.js";
import { createAgentDelegationTool } from "../src/tools/agent-delegation.js";
import { registerWebApi } from "../src/web-api.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 6 });
  await migrateDatabase(database);
});

afterAll(async () => {
  await database?.end();
});

integration("analytics workflow end to end", () => {
  it("runs all specialists and reads the persisted final artifacts through the API", async () => {
    const agents = new AgentPool();
    for (const plugin of await loadExternalAgentPlugins(DEFAULT_AGENT_MANIFESTS)) {
      agents.register(plugin);
    }
    const tools = await loadToolPool(["src/tools/warehouse.ts"], { database });
    tools.register(createAgentCatalogTool(agents));
    // Python agents call the model only through the host; tools stay host-side.
    const runtime = {
      async prompt(input: { agentId: string; system: string; prompt: string }) {
        const json = input.system.includes("JSON Schema");
        if (input.agentId === "orchestrator" && json) {
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
            title: "Monthly revenue",
          });
        }
        if (input.agentId === "report") throw new Error("Use deterministic report draft");
        if (input.agentId === "orchestrator") {
          const artifactIds = [
            ...new Set(
              input.prompt.match(
                /\b(?:ds_(?:[a-zA-Z0-9]{12}|[a-f0-9]{24})|ch_[a-zA-Z0-9]{12}|rp_[a-zA-Z0-9]{12})\b/g,
              ) ?? [],
            ),
          ];
          return `Analysis complete. Verified artifacts: ${artifactIds.join(", ")}`;
        }
        return `${input.agentId} findings for the supplied dataset.`;
      },
    };
    tools.register(
      createAgentDelegationTool({
        database,
        pluginRegistry: agents,
        pool: tools,
        runtime: runtime as never,
      }),
    );

    const app = new Hono();
    registerWebApi(app, {
      database,
      pluginRegistry: agents,
      pool: tools,
      runtime: runtime as never,
    });

    let userId: string | undefined;
    let taskId: string | undefined;
    try {
      const userResponse = await app.request("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `E2E ${randomUUID()}` }),
      });
      expect(userResponse.status).toBe(201);
      userId = ((await userResponse.json()) as { id: string }).id;

      const startResponse = await app.request("/api/agents/orchestrator/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId },
        body: JSON.stringify({
          content:
            "Analyze monthly_sales, compare January and February, explain the trend, and create a chart report.",
        }),
      });
      expect(startResponse.status).toBe(202);
      taskId = ((await startResponse.json()) as { task_id: string }).task_id;

      const deadline = Date.now() + 45_000;
      let detailResponse: Response;
      let detail: {
        task: { status: string };
        invocations: Array<{ agent: string; status: string }>;
      };
      do {
        detailResponse = await app.request(`/api/tasks/${taskId}`, {
          headers: { "X-User-Id": userId },
        });
        detail = (await detailResponse.json()) as typeof detail;
        if (detail.task?.status !== "running") break;
        await new Promise((resolve) => setTimeout(resolve, 25));
      } while (Date.now() < deadline);
      if (detail.task.status === "running") {
        await app.request(`/api/tasks/${taskId}/cancel`, {
          method: "POST",
          headers: { "X-User-Id": userId },
        });
        const cancelDeadline = Date.now() + 2_000;
        while (detail.task.status === "running" && Date.now() < cancelDeadline) {
          await new Promise((resolve) => setTimeout(resolve, 25));
          detailResponse = await app.request(`/api/tasks/${taskId}`, {
            headers: { "X-User-Id": userId },
          });
          detail = (await detailResponse.json()) as typeof detail;
        }
      }

      expect(detailResponse.status).toBe(200);
      expect(detail.task.status).toBe("completed");
      expect(detail.invocations.map(({ agent, status }) => [agent, status])).toEqual(
        expect.arrayContaining([
          ["orchestrator", "completed"],
          ["data", "completed"],
          ["compare", "completed"],
          ["insight", "completed"],
          ["visualize", "completed"],
          ["report", "completed"],
        ]),
      );

      const messagesResponse = await app.request("/api/agents/orchestrator/messages", {
        headers: { "X-User-Id": userId },
      });
      const messages = (await messagesResponse.json()) as {
        messages: Array<{ role: string; content: string }>;
      };
      const finalMessage = messages.messages.findLast(({ role }) => role === "assistant");
      expect(finalMessage?.content).toContain("Analysis complete");
      expect(finalMessage?.content).toContain("ch_");

      const [datasetId, chartId, reportId] = [
        finalMessage?.content.match(/\bds_(?:[a-zA-Z0-9]{12}|[a-f0-9]{24})\b/)?.[0],
        finalMessage?.content.match(/\bch_[a-zA-Z0-9]{12}\b/)?.[0],
        finalMessage?.content.match(/\brp_[a-zA-Z0-9]{12}\b/)?.[0],
      ];
      expect(datasetId).toBeDefined();
      expect(chartId).toBeDefined();
      expect(reportId).toBeDefined();

      for (const path of [
        `/api/datasets/${datasetId}`,
        `/api/charts/${chartId}`,
        `/api/reports/${reportId}`,
      ]) {
        const response = await app.request(path, { headers: { "X-User-Id": userId } });
        expect(response.status).toBe(200);
      }

      const reportResponse = await app.request(`/api/reports/${reportId}`, {
        headers: { "X-User-Id": userId },
      });
      const report = (await reportResponse.json()) as { markdown: string };
      expect(report.markdown).toContain("## Comparison");
      expect(report.markdown).toContain("## Insight");
      expect(report.markdown).toContain("## Visualization");
      expect(report.markdown).toContain(`{{chart:${chartId}}}`);
    } finally {
      if (userId) {
        await database.query("DELETE FROM web_reports WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_charts WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_datasets WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_messages WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_invocations WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_tasks WHERE user_id = $1", [userId]);
        await database.query("DELETE FROM web_users WHERE id = $1", [userId]);
      }
    }
  }, 60_000);
});
