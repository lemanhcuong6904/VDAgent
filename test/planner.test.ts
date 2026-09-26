import { describe, expect, it } from "vitest";
import {
  buildCapabilityPlan,
  MissingCapabilityError,
  proposeCapabilityPlan,
  validatePlan,
} from "../src/planner.js";

const catalog = {
  findByCapability(capability: string) {
    const agents = {
      "warehouse.query": "warehouse-agent",
      "dataset.compare": "comparison-agent",
      "dataset.insight": "insight-agent",
      "dataset.visualize": "chart-agent",
      "dataset.report": "report-agent",
    } as Record<string, string | undefined>;
    const id = agents[capability];
    return id
      ? [{ id, version: "1.0.0", description: capability, capabilities: [capability] }]
      : [];
  },
};

describe("capability planner", () => {
  const typedCatalog = {
    findByCapability(capability: string) {
      if (capability === "warehouse.query") {
        return [{ id: "data", version: "1", description: "data", capabilities: [capability] }];
      }
      return [];
    },
  };

  it("validates model-proposed typed plans against the catalog", async () => {
    const plan = await proposeCapabilityPlan("list revenue", typedCatalog, async () =>
      JSON.stringify({
        version: "plan.v1",
        goal: "ignored",
        steps: [{ id: "query", capability: "warehouse.query", agentId: "data", dependsOn: [] }],
      }),
    );
    if (!plan) throw new Error("Expected a typed plan");
    expect(plan?.steps[0]?.agentId).toBe("data");
    expect(validatePlan(plan, typedCatalog).version).toBe("plan.v1");
  });

  it("creates a bounded plan from capabilities instead of concrete agent ids", () => {
    const plan = buildCapabilityPlan(
      "Compare revenue by region, explain the trend, and save a chart report",
      catalog,
    );

    expect(plan?.steps.map(({ capability }) => capability)).toEqual([
      "warehouse.query",
      "dataset.compare",
      "dataset.insight",
      "dataset.visualize",
      "dataset.report",
    ]);
    expect(plan?.steps.map(({ agentId }) => agentId)).toEqual([
      "warehouse-agent",
      "comparison-agent",
      "insight-agent",
      "chart-agent",
      "report-agent",
    ]);
    expect(plan?.steps.at(-1)?.dependsOn).toEqual(["dataset_visualize"]);
  });

  it("returns no data plan for a non-data request", () => {
    expect(buildCapabilityPlan("What is the capital of France?", catalog)).toBeUndefined();
  });

  it("fails explicitly when a requested capability is unavailable", () => {
    expect(() =>
      buildCapabilityPlan("Create a chart from the warehouse data", {
        findByCapability: (capability) =>
          capability === "warehouse.query" ? catalog.findByCapability(capability) : [],
      }),
    ).toThrow(MissingCapabilityError);
  });
});
