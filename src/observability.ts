import { randomUUID } from "node:crypto";

export interface TraceContext {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
}

export interface SpanHandle {
  context: TraceContext;
  setAttribute(name: string, value: string | number | boolean): void;
  recordException(error: unknown): void;
  end(status?: "ok" | "error"): void;
}

export interface Telemetry {
  startSpan(
    name: string,
    context?: TraceContext,
    attributes?: Record<string, string | number | boolean>,
  ): SpanHandle;
  count(name: string, value?: number, attributes?: Record<string, string | number | boolean>): void;
  observe(
    name: string,
    value: number,
    attributes?: Record<string, string | number | boolean>,
  ): void;
}

export interface StructuredLogger {
  info(message: string, fields?: Record<string, unknown>): void;
  warn(message: string, fields?: Record<string, unknown>): void;
  error(message: string, fields?: Record<string, unknown>): void;
}

export function newTraceContext(parent?: TraceContext): TraceContext {
  return {
    traceId: parent?.traceId ?? randomUUID(),
    spanId: randomUUID(),
    parentSpanId: parent?.spanId,
  };
}

export class NoopTelemetry implements Telemetry {
  startSpan(_name: string, context?: TraceContext): SpanHandle {
    const spanContext = newTraceContext(context);
    return {
      context: spanContext,
      setAttribute() {},
      recordException() {},
      end() {},
    };
  }

  count() {}

  observe() {}
}

export class JsonTelemetry implements Telemetry {
  constructor(private readonly logger: StructuredLogger = new JsonLogger(process.stderr)) {}

  startSpan(
    name: string,
    context?: TraceContext,
    attributes: Record<string, string | number | boolean> = {},
  ): SpanHandle {
    const spanContext = newTraceContext(context);
    const started = performance.now();
    let status: "ok" | "error" = "ok";
    let exception: string | undefined;
    this.logger.info("trace.start", {
      trace_id: spanContext.traceId,
      span_id: spanContext.spanId,
      parent_span_id: spanContext.parentSpanId,
      span: name,
      attributes,
    });
    return {
      context: spanContext,
      setAttribute: (key, value) => {
        attributes[key] = value;
      },
      recordException: (error) => {
        status = "error";
        exception = error instanceof Error ? error.name : "unknown_error";
      },
      end: (result) => {
        if (result) status = result;
        this.logger.info("trace.end", {
          trace_id: spanContext.traceId,
          span_id: spanContext.spanId,
          span: name,
          status,
          duration_ms: Math.round(performance.now() - started),
          exception,
          attributes,
        });
      },
    };
  }

  count(name: string, value = 1, attributes: Record<string, string | number | boolean> = {}): void {
    this.logger.info("metric.count", { metric: name, value, attributes });
  }

  observe(
    name: string,
    value: number,
    attributes: Record<string, string | number | boolean> = {},
  ): void {
    this.logger.info("metric.observe", { metric: name, value, attributes });
  }
}

export function createTelemetry(env: NodeJS.ProcessEnv = process.env): Telemetry | undefined {
  return env.TELEMETRY_MODE === "json" ? new JsonTelemetry() : undefined;
}

export class JsonLogger implements StructuredLogger {
  constructor(private readonly stream: NodeJS.WriteStream = process.stdout) {}

  info(message: string, fields?: Record<string, unknown>): void {
    this.write("info", message, fields);
  }

  warn(message: string, fields?: Record<string, unknown>): void {
    this.write("warn", message, fields);
  }

  error(message: string, fields?: Record<string, unknown>): void {
    this.write("error", message, fields);
  }

  private write(level: string, message: string, fields?: Record<string, unknown>): void {
    this.stream.write(
      `${JSON.stringify({
        timestamp: new Date().toISOString(),
        level,
        message,
        ...redactFields(fields ?? {}),
      })}\n`,
    );
  }
}

function redactFields(fields: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(fields)) {
    if (/(token|secret|password|api[_-]?key|authorization|prompt|content|memory)/i.test(key)) {
      result[key] = "[redacted]";
    } else if (typeof value === "string" && value.length > 500) {
      result[key] = `${value.slice(0, 500)}...[truncated]`;
    } else {
      result[key] = value;
    }
  }
  return result;
}
