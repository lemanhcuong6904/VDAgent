/**
 * OTel Observability Tests - M11.4
 * Validates OTel traces/metrics/logs with redaction, correlation and exporter-failure isolation
 */

import { context, SpanStatusCode, type TracerProvider } from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import {
  type DataPoint,
  MeterProvider,
  type MetricData,
  MetricReader,
} from "@opentelemetry/sdk-metrics";
import {
  BasicTracerProvider,
  InMemorySpanExporter,
  type ReadableSpan,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { migrateDatabase } from "../src/database.js";
import {
  type LogEntry,
  type LogLevel,
  Observability,
  REDACTED,
} from "../src/otel-observability.js";

class TestMetricReader extends MetricReader {
  protected async onForceFlush(): Promise<void> {}
  protected async onShutdown(): Promise<void> {}
}

const contextManager = new AsyncLocalStorageContextManager();
let spanExporter: InMemorySpanExporter;
let metricReader: TestMetricReader;
let tracerProvider: BasicTracerProvider;
let meterProvider: MeterProvider;
let lines: Array<{ level: LogLevel; entry: LogEntry }>;

function build(overrides: Partial<ConstructorParameters<typeof Observability>[0]> = {}) {
  return new Observability({
    serviceName: "test-service",
    serviceVersion: "1.0.0",
    tracerProvider,
    meterProvider,
    write: (level, line) => lines.push({ level, entry: JSON.parse(line) as LogEntry }),
    ...overrides,
  });
}

function finishedSpan(name: string): ReadableSpan {
  const span = spanExporter.getFinishedSpans().find((candidate) => candidate.name === name);
  if (!span) throw new Error(`span ${name} was not exported`);
  return span;
}

async function metric(name: string): Promise<MetricData> {
  const { resourceMetrics } = await metricReader.collect();
  const found = resourceMetrics.scopeMetrics
    .flatMap((scope) => scope.metrics)
    .find((candidate) => candidate.descriptor.name === name);
  if (!found) throw new Error(`metric ${name} was not collected`);
  return found;
}

function failingTracerProvider(): TracerProvider {
  return {
    getTracer: () => ({
      startSpan: () => {
        throw new Error("exporter down");
      },
      startActiveSpan: () => {
        throw new Error("exporter down");
      },
    }),
  };
}

beforeAll(() => {
  context.setGlobalContextManager(contextManager.enable());
});

afterAll(() => {
  context.disable();
});

beforeEach(() => {
  spanExporter = new InMemorySpanExporter();
  tracerProvider = new BasicTracerProvider({
    spanProcessors: [new SimpleSpanProcessor(spanExporter)],
  });
  metricReader = new TestMetricReader();
  meterProvider = new MeterProvider({ readers: [metricReader] });
  lines = [];
});

describe("Observability - M11.4", () => {
  describe("traces", () => {
    it("exports a span with redacted attributes", () => {
      const observability = build();
      const span = observability.startSpan("run.execute", {
        workspace_id: "ws_test",
        api_key: "sk_live_should_not_leak",
        note: "contact alice@example.com",
      });
      expect(span.isRecording()).toBe(true);
      span.end();

      const exported = finishedSpan("run.execute");
      expect(exported.attributes.workspace_id).toBe("ws_test");
      expect(exported.attributes.api_key).toBe(REDACTED);
      expect(exported.attributes.note).toBe(`contact ${REDACTED}`);
      expect(JSON.stringify(exported.attributes)).not.toContain("sk_live");
    });

    it("marks withSpan success as OK and returns the result", async () => {
      const observability = build();
      const result = await observability.withSpan(
        "run.ok",
        { run_id: "run_1" },
        async () => "done",
      );

      expect(result).toBe("done");
      expect(finishedSpan("run.ok").status.code).toBe(SpanStatusCode.OK);
    });

    it("records a redacted exception and rethrows the caller's error", async () => {
      const observability = build();
      const failure = new Error("login failed for bob@example.com");

      await expect(
        observability.withSpan("run.fail", {}, async () => {
          throw failure;
        }),
      ).rejects.toBe(failure);

      const exported = finishedSpan("run.fail");
      expect(exported.status.code).toBe(SpanStatusCode.ERROR);
      expect(exported.status.message).toBe(`login failed for ${REDACTED}`);
      expect(exported.events.some((event) => event.name === "exception")).toBe(true);
      expect(JSON.stringify(exported.events)).not.toContain("bob@example.com");
    });

    it("parents nested spans under the active span", async () => {
      const observability = build();
      await observability.withSpan("parent", {}, async () => {
        await observability.withSpan("child", {}, async () => undefined);
      });

      const parent = finishedSpan("parent");
      const child = finishedSpan("child");
      expect(child.spanContext().traceId).toBe(parent.spanContext().traceId);
      expect(child.parentSpanContext?.spanId).toBe(parent.spanContext().spanId);
    });
  });

  describe("correlation", () => {
    it("returns the active span's trace context", async () => {
      const observability = build();
      let captured: ReturnType<Observability["getTraceContext"]> = null;
      await observability.withSpan("correlated", {}, async () => {
        captured = observability.getTraceContext();
      });

      const exported = finishedSpan("correlated");
      expect(captured).toEqual({
        traceId: exported.spanContext().traceId,
        spanId: exported.spanContext().spanId,
        traceFlags: exported.spanContext().traceFlags,
      });
    });

    it("returns null outside any span", () => {
      expect(build().getTraceContext()).toBeNull();
    });

    it("stamps logs emitted inside a span with its trace and span id", async () => {
      const observability = build();
      await observability.withSpan("logging", {}, async () => {
        observability.log("info", "inside span");
      });
      observability.log("info", "outside span");

      const exported = finishedSpan("logging");
      expect(lines[0].entry.trace?.traceId).toBe(exported.spanContext().traceId);
      expect(lines[0].entry.trace?.spanId).toBe(exported.spanContext().spanId);
      expect(lines[1].entry.trace).toBeNull();
    });
  });

  describe("metrics", () => {
    it("accumulates counters on a single reused instrument", async () => {
      const observability = build();
      observability.recordCounter("runs.completed", 2, { workspace_id: "ws_a", status: "success" });
      observability.recordCounter("runs.completed", 3, { workspace_id: "ws_a", status: "success" });

      const collected = await metric("runs.completed");
      expect(collected.dataPoints).toHaveLength(1);
      expect(collected.dataPoints[0].value).toBe(5);
      expect(collected.dataPoints[0].attributes).toEqual({
        workspace_id: "ws_a",
        status: "success",
      });
    });

    it("records histogram observations", async () => {
      const observability = build();
      observability.recordHistogram("run.duration_ms", 120, { agent_type: "analytics" });
      observability.recordHistogram("run.duration_ms", 80, { agent_type: "analytics" });

      const point = (await metric("run.duration_ms")).dataPoints[0] as DataPoint<{
        count: number;
        sum?: number;
      }>;
      expect(point.value.count).toBe(2);
      expect(point.value.sum).toBe(200);
    });

    it("keeps the last gauge value", async () => {
      const observability = build();
      observability.recordGauge("outbox.lag", 10, { workspace_id: "ws_a" });
      observability.recordGauge("outbox.lag", 4, { workspace_id: "ws_a" });

      expect((await metric("outbox.lag")).dataPoints[0].value).toBe(4);
    });

    it("drops sensitive label keys and redacts label values", async () => {
      const observability = build();
      observability.recordCounter("labels.checked", 1, {
        workspace_id: "ws_a",
        password: "hunter2",
        owner: "carol@example.com",
      });

      const attributes = (await metric("labels.checked")).dataPoints[0].attributes;
      expect(attributes).toEqual({ workspace_id: "ws_a", owner: REDACTED });
      expect(JSON.stringify(attributes)).not.toContain("hunter2");
    });
  });

  describe("log redaction", () => {
    it("routes levels to the sink with structured JSON", () => {
      const observability = build();
      observability.log("info", "started", { run_id: "run_1" });
      observability.log("warn", "slow");
      observability.log("error", "failed", { error_code: "E_TIMEOUT" });

      expect(lines.map((line) => line.level)).toEqual(["info", "warn", "error"]);
      expect(lines[0].entry.data).toEqual({ run_id: "run_1" });
      expect(lines[2].entry.data).toEqual({ error_code: "E_TIMEOUT" });
      expect(Date.parse(lines[0].entry.timestamp)).not.toBeNaN();
    });

    it("redacts sensitive keys, including prompts and model payloads", () => {
      build().log("info", "model call", {
        username: "alice",
        password: "hunter2",
        api_key: "key_abc123",
        authorization: "Basic abc",
        prompt: "private question",
        model_input: "private input",
        model_output: "private output",
      });

      const { data } = lines[0].entry;
      expect(data.username).toBe("alice");
      for (const key of [
        "password",
        "api_key",
        "authorization",
        "prompt",
        "model_input",
        "model_output",
      ]) {
        expect(data[key]).toBe(REDACTED);
      }
      expect(JSON.stringify(lines[0].entry)).not.toMatch(/hunter2|private (question|input|output)/);
    });

    it("redacts nested objects and arrays", () => {
      build().log("info", "nested", {
        config: { database: { user: "admin", password: "hunter2" } },
        recipients: ["dave@example.com", { token: "t0k" }],
      });

      const data = lines[0].entry.data as {
        config: { database: Record<string, unknown> };
        recipients: unknown[];
      };
      expect(data.config.database).toEqual({ user: "admin", password: REDACTED });
      expect(data.recipients).toEqual([REDACTED, { token: REDACTED }]);
    });

    it.each([
      ["inline secrets", "connect password=hunter2 host=db", "hunter2"],
      ["bearer tokens", "Authorization: Bearer abc123.def456", "abc123.def456"],
      ["email addresses", "user alice@example.com signed in", "alice@example.com"],
      [
        "AWS access keys",
        `key AKIA${"ABCDEFGHIJKLMNOP"} used`,
        ["AKIA", "ABCDEFGHIJKLMNOP"].join(""),
      ],
      ["credit cards", "card 4111 1111 1111 1111 declined", "4111 1111 1111 1111"],
      ["SSNs", "ssn 123-45-6789 on file", "123-45-6789"],
      [
        "long key material",
        "key abcdef1234567890abcdef1234567890 rotated",
        "abcdef1234567890abcdef1234567890",
      ],
    ])("redacts %s in messages", (_label, message, secret) => {
      build().log("info", message);
      expect(lines[0].entry.message).not.toContain(secret);
      expect(lines[0].entry.message).toContain(REDACTED);
    });

    it("leaves ordinary identifiers intact", () => {
      build().log("info", "run run_42 finished for ws_prod in 1200ms");
      expect(lines[0].entry.message).toBe("run run_42 finished for ws_prod in 1200ms");
    });

    it("bounds redaction depth on deeply nested data", () => {
      let deep: Record<string, unknown> = { leaf: "value" };
      for (let index = 0; index < 20; index += 1) deep = { next: deep };

      expect(() => build().log("info", "deep", deep)).not.toThrow();
      expect(JSON.stringify(lines[0].entry.data)).toContain(REDACTED);
    });
  });

  describe("exporter failure isolation", () => {
    it("returns a non-recording span when the tracer throws", () => {
      const observability = build({ tracerProvider: failingTracerProvider() });
      const span = observability.startSpan("broken");

      expect(span.isRecording()).toBe(false);
      expect(() => span.end()).not.toThrow();
    });

    it("still runs the wrapped operation when tracing is broken", async () => {
      const observability = build({ tracerProvider: failingTracerProvider() });
      await expect(observability.withSpan("broken", {}, async () => 42)).resolves.toBe(42);
      expect(observability.getTraceContext()).toBeNull();
    });

    it("swallows meter failures", () => {
      const brokenMeter = {
        getMeter: () => {
          throw new Error("meter down");
        },
      };
      expect(() => build({ meterProvider: brokenMeter as never })).toThrow("meter down");

      const throwing = () => {
        throw new Error("instrument down");
      };
      const observability = build({
        meterProvider: {
          getMeter: () =>
            ({
              createCounter: throwing,
              createHistogram: throwing,
              createGauge: throwing,
            }) as never,
        },
      });
      expect(() => {
        observability.recordCounter("c", 1);
        observability.recordHistogram("h", 1);
        observability.recordGauge("g", 1);
      }).not.toThrow();
    });

    it("swallows log sink failures", () => {
      const observability = build({
        write: () => {
          throw new Error("stdout closed");
        },
      });
      expect(() => observability.log("error", "lost")).not.toThrow();
    });

    it("propagates failures when isolation is disabled", () => {
      const observability = build({
        tracerProvider: failingTracerProvider(),
        exporterIsolation: false,
      });
      expect(() => observability.startSpan("strict")).toThrow("exporter down");
    });

    it("reports isolated failures without leaking the error message", () => {
      const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
      try {
        build({ tracerProvider: failingTracerProvider() }).startSpan("broken");
        const report = String(stderr.mock.calls.at(-1)?.[0]);
        expect(report).toContain("telemetry.isolated_failure");
        expect(report).not.toContain("exporter down");
      } finally {
        stderr.mockRestore();
      }
    });
  });

  describe("log persistence", () => {
    it("persists only warn and error logs, redacted and correlated", async () => {
      const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 1 });
      const observability = build({ database: { query } as unknown as Pool });

      await observability.withSpan("persisted", {}, async () => {
        observability.log("info", "not persisted");
        observability.log("error", "failed for erin@example.com", { secret: "s3cr3t" });
      });
      observability.log("warn", "slow outside span");
      await observability.flush();

      expect(query).toHaveBeenCalledTimes(2);
      const [, errorParams] = query.mock.calls[0];
      const exported = finishedSpan("persisted");
      expect(errorParams[1]).toBe("error");
      expect(errorParams[2]).toBe(`failed for ${REDACTED}`);
      expect(JSON.parse(errorParams[3])).toEqual({ secret: REDACTED });
      expect(errorParams[4]).toBe(exported.spanContext().traceId);
      expect(errorParams[5]).toBe(exported.spanContext().spanId);

      const [, warnParams] = query.mock.calls[1];
      expect(warnParams[1]).toBe("warn");
      expect(warnParams[4]).toBeNull();
      expect(warnParams[5]).toBeNull();
    });

    it("never fails the caller when persistence rejects", async () => {
      const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
      try {
        const query = vi.fn().mockRejectedValue(new Error("connection refused"));
        const observability = build({ database: { query } as unknown as Pool });

        expect(() => observability.log("error", "db down")).not.toThrow();
        await expect(observability.flush()).resolves.toBeUndefined();
        expect(lines).toHaveLength(1);
      } finally {
        stderr.mockRestore();
      }
    });
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("Observability - M11.4 (PostgreSQL)", () => {
  let database: Pool;

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 2 });
    await migrateDatabase(database);
  });

  afterAll(async () => {
    await database?.end();
  });

  it("writes redacted, correlated rows to observability_logs", async () => {
    const marker = `m11_4_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const observability = build({ database });

    await observability.withSpan("db.persisted", {}, async () => {
      observability.log("error", `${marker} failed for frank@example.com`, { token: "t0k" });
    });
    await observability.flush();

    const exported = finishedSpan("db.persisted");
    const result = await database.query<{
      level: string;
      message: string;
      data: Record<string, unknown>;
      trace_id: string | null;
      span_id: string | null;
    }>(
      "SELECT level, message, data, trace_id, span_id FROM observability_logs WHERE message LIKE $1",
      [`${marker}%`],
    );
    try {
      expect(result.rows).toHaveLength(1);
      expect(result.rows[0]).toEqual({
        level: "error",
        message: `${marker} failed for ${REDACTED}`,
        data: { token: REDACTED },
        trace_id: exported.spanContext().traceId,
        span_id: exported.spanContext().spanId,
      });
    } finally {
      await database.query("DELETE FROM observability_logs WHERE message LIKE $1", [`${marker}%`]);
    }
  });
});
