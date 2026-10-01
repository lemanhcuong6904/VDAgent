import { describe, expect, it } from "vitest";
import { assertSecureSecret, isAuthorizedAgent } from "../src/agent-auth.js";
import { createWebAuth, issueWebSession, verifyWebSession } from "../src/web-auth.js";

describe("agent MCP authentication", () => {
  it("rejects placeholder secrets in secure mode", () => {
    expect(() => assertSecureSecret("API_TOKEN", "replace-with-a-long-local-token")).toThrow();
    expect(() => assertSecureSecret("API_TOKEN", "a".repeat(32))).not.toThrow();
  });

  it("issues and verifies expiring web sessions", () => {
    const config = createWebAuth({ WEB_AUTH_MODE: "session", WEB_AUTH_SECRET: "s".repeat(40) });
    const token = issueWebSession("user-1", config, 100);
    expect(verifyWebSession(token, config, 101)?.userId).toBe("user-1");
    expect(verifyWebSession(token, config, 100 + config.ttlSeconds)).toBeUndefined();
    expect(verifyWebSession(`${token}x`, config, 101)).toBeUndefined();
  });

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
