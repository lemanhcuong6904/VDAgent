import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { describe, expect, it } from "vitest";
import { createOutboxFanout } from "../../src/outbox-consumers.js";
import { RuntimeContextShaper } from "../../src/session/runtime-context.js";

const user = (text: string) => ({ role: "user", content: text, timestamp: 0 }) as AgentMessage;
const assistant = (text: string) =>
  ({
    role: "assistant",
    content: [{ type: "text", text }],
    timestamp: 0,
  }) as unknown as AgentMessage;
const toolResult = (text: string) =>
  ({
    role: "toolResult",
    toolCallId: "call-1",
    toolName: "warehouse.run_query",
    content: [{ type: "text", text }],
    isError: false,
    timestamp: 0,
  }) as AgentMessage;

describe("runtime context shaping (M7)", () => {
  it("externalizes oversized tool results into a bounded preview", async () => {
    const shaper = new RuntimeContextShaper("s1", {
      maxTokens: 100_000,
      marginTokens: 100,
      maxInlineBytes: 2048,
    });
    const shaped = await shaper.shape([user("q"), toolResult("x".repeat(50_000))]);
    const text = (shaped[1] as { content: Array<{ text: string }> }).content[0]?.text ?? "";
    expect(Buffer.byteLength(text)).toBeLessThan(2048);
    expect(text).toContain("tool result truncated: 50000 bytes");
    expect(shaper.tree.getAllEntries().length).toBeGreaterThan(0);
  });

  it("drops leading turns at user boundaries and always keeps the latest user turn", async () => {
    const shaper = new RuntimeContextShaper("s2", {
      maxTokens: 400,
      marginTokens: 10,
      maxInlineBytes: 100_000,
    });
    const history = [
      user("old question"),
      assistant("y".repeat(2000)),
      user("latest question"),
      toolResult("small result"),
    ];
    const shaped = await shaper.shape(history);
    expect(shaped[0]).toBe(history[2]);
    expect(shaped).toHaveLength(2);
    const compaction = shaper.tree.getAllEntries().find((entry) => entry.type === "compaction");
    expect(compaction).toMatchObject({ compactedUpTo: 2 });
    const tiny = new RuntimeContextShaper("s3", {
      maxTokens: 5,
      marginTokens: 0,
      maxInlineBytes: 100_000,
    });
    expect((await tiny.shape([user("z".repeat(500))])).length).toBe(1);
  });
});

describe("outbox fan-out (M6)", () => {
  it("dedupes redelivered events per consumer and dead-letters consumer failures", async () => {
    const seen: string[] = [];
    let fail = true;
    const { outbox, dispatch } = createOutboxFanout([
      {
        consumerId: "ok",
        eventTypes: ["*"],
        handler: async (event) => {
          seen.push(`ok:${event.eventId}`);
        },
      },
      {
        consumerId: "flaky",
        eventTypes: ["run.completed"],
        handler: async (event) => {
          if (fail) throw new Error("down");
          seen.push(`flaky:${event.eventId}`);
        },
      },
    ]);
    const row = { id: 7, run_id: "run_1", event_type: "run.completed", payload: {}, attempts: 0 };
    await expect(dispatch(row)).rejects.toThrow("down");
    expect(outbox.getDeadLetters("flaky")).toHaveLength(1);
    fail = false;
    await dispatch(row); // durable redelivery: "ok" must not run twice
    expect(seen).toEqual(["ok:7", "flaky:7"]);
    expect(outbox.getCheckpoint("ok")?.lastProcessedEventId).toBe("7");
  });
});
