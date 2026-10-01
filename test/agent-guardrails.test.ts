import { describe, expect, it } from "vitest";
import { greetingReply } from "../src/agent-guardrails.js";

describe("agent response guardrails", () => {
  it("answers standalone greetings without starting an analysis turn", () => {
    expect(greetingReply("hello!")).toBe("Hello! How can I help?");
    expect(greetingReply("  xin chào  ")).toBe("Chào bạn! Mình có thể giúp gì?");
    expect(greetingReply("hello, compare revenue by region")).toBeNull();
  });
});
