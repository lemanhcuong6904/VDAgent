import { describe, expect, it } from "vitest";
import { createDefaultModelRegistry, ModelRegistry } from "../src/model-registry.js";

describe("ModelRegistry", () => {
  it("registers profiles and selects them by capability", () => {
    const registry = new ModelRegistry();
    registry.register({
      id: "fast",
      provider: "openai",
      model: "gpt-test",
      capabilities: ["general", "tool-calling"],
    });
    registry.register({
      id: "reasoning",
      provider: "anthropic",
      model: "claude-test",
      capabilities: ["reasoning"],
    });

    expect(registry.findByCapability("REASONING").map(({ id }) => id)).toEqual(["reasoning"]);
    expect(registry.require("fast").model).toBe("gpt-test");
    expect(() => registry.register({ ...registry.require("fast") })).toThrow("already registered");
  });

  it("builds a deterministic default profile from environment configuration", () => {
    const registry = createDefaultModelRegistry({
      PI_DEFAULT_PROVIDER: "test-provider",
      PI_DEFAULT_MODEL: "test-model",
    });
    expect(registry.require("default")).toMatchObject({
      provider: "test-provider",
      model: "test-model",
    });
  });

  it("loads additional provider profiles from configuration without code changes", () => {
    const registry = createDefaultModelRegistry({
      MODEL_PROFILES_JSON: JSON.stringify([
        {
          id: "reasoning",
          provider: "anthropic",
          model: "claude-test",
          capabilities: ["reasoning", "tool-calling"],
        },
      ]),
    });
    expect(registry.require("reasoning")).toMatchObject({
      provider: "anthropic",
      model: "claude-test",
    });
  });
});
