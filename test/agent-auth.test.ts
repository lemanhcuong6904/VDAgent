import { describe, expect, it } from "vitest";
import { isAuthorizedAgent } from "../src/agent-auth.js";

describe("agent MCP authentication", () => {
  it("binds each MCP token to one registered agent identity", () => {
    const env = {
      AGENT_TOKEN_EXAMPLE_SUMMARY: "example-token",
      AGENT_TOKEN_ANALYSIS: "analysis-token",
    };
    const registered = new Set(["example.summary", "analysis"]);
    const hasAgent = (id: string) => registered.has(id);

    expect(isAuthorizedAgent("example.summary", "Bearer example-token", env, hasAgent)).toBe(true);
    expect(isAuthorizedAgent("example.summary", "Bearer analysis-token", env, hasAgent)).toBe(
      false,
    );
    expect(isAuthorizedAgent("unregistered", "Bearer example-token", env, hasAgent)).toBe(false);
  });
});
