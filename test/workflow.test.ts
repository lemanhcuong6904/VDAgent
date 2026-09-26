import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import { WorkflowRegistry } from "../src/workflow.js";

const base = {
  triggerSchema: Type.Object({}),
  stateSchema: Type.Object({}, { additionalProperties: true }),
};

describe("workflow registry", () => {
  it("registers versioned acyclic workflow specs", () => {
    const registry = new WorkflowRegistry();
    registry.register({
      ...base,
      id: "analytics",
      version: "1.0.0",
      steps: [
        { id: "discover", capability: "warehouse.catalog" },
        { id: "query", capability: "warehouse.query", dependsOn: ["discover"] },
      ],
    });
    expect(registry.get("analytics")?.version).toBe("1.0.0");
  });

  it("rejects cycles and unknown dependencies", () => {
    const registry = new WorkflowRegistry();
    expect(() =>
      registry.register({
        ...base,
        id: "broken",
        version: "1",
        steps: [
          { id: "a", capability: "one", dependsOn: ["b"] },
          { id: "b", capability: "two", dependsOn: ["a"] },
        ],
      }),
    ).toThrow("acyclic");
  });
});
