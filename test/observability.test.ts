import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { JsonLogger, newTraceContext } from "../src/observability.js";

describe("observability primitives", () => {
  it("creates child trace context and redacts sensitive structured fields", () => {
    const parent = newTraceContext();
    const child = newTraceContext(parent);
    expect(child.traceId).toBe(parent.traceId);
    expect(child.parentSpanId).toBe(parent.spanId);

    const stream = new PassThrough();
    const chunks: Buffer[] = [];
    stream.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
    const logger = new JsonLogger(stream as never);
    logger.info("agent run", {
      task_id: "task-1",
      api_key: "secret",
      prompt: "private prompt",
    });
    const output = Buffer.concat(chunks).toString("utf8");
    expect(output).toContain('"task_id":"task-1"');
    expect(output).toContain('"api_key":"[redacted]"');
    expect(output).toContain('"prompt":"[redacted]"');
    expect(output).not.toContain("private prompt");
  });
});
