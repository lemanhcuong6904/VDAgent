/**
 * Observability - M11.4
 * OTel traces/metrics/logs with redaction, correlation and exporter-failure isolation
 */

import {
  type Counter,
  context,
  type Gauge,
  type Histogram,
  INVALID_SPAN_CONTEXT,
  type Meter,
  type MeterProvider,
  metrics,
  type Span,
  SpanStatusCode,
  type Tracer,
  type TracerProvider,
  trace,
} from "@opentelemetry/api";
import type { Pool } from "pg";

export type LogLevel = "debug" | "info" | "warn" | "error";
type AttributeValue = string | number | boolean;

export interface ObservabilityConfig {
  serviceName: string;
  serviceVersion: string;
  /** Defaults to the globally registered OTel provider. */
  tracerProvider?: TracerProvider;
  /** Defaults to the globally registered OTel provider. */
  meterProvider?: MeterProvider;
  /** When set, warn/error logs are persisted to observability_logs. */
  database?: Pool;
  /** Replaces the default value patterns. */
  redactPatterns?: RegExp[];
  /** When true (default), telemetry failures never propagate to callers. */
  exporterIsolation?: boolean;
  /** Log sink; defaults to one JSON line per entry on stdout/stderr. */
  write?: (level: LogLevel, line: string) => void;
}

export interface TraceContext {
  traceId: string;
  spanId: string;
  traceFlags: number;
}

export interface MetricLabels {
  workspace_id?: string;
  run_id?: string;
  agent_type?: string;
  status?: string;
  [key: string]: string | undefined;
}

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  data: Record<string, unknown>;
  trace: TraceContext | null;
}

export const REDACTED = "[REDACTED]";

const SENSITIVE_KEY =
  /(password|passwd|secret|token|api[_-]?key|credential|authorization|private[_-]?key|ssn|credit[_-]?card|prompt|model[_-]?(input|output)|cookie|session[_-]?key)/i;

const DEFAULT_REDACT_PATTERNS: readonly RegExp[] = [
  // key=value / key: value secrets embedded in free text
  /\b(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;&]+/gi,
  // Bearer tokens
  /Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi,
  // AWS access key IDs
  /\bAKIA[0-9A-Z]{16}\b/g,
  // Email addresses
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
  // Credit card numbers
  /\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b/g,
  // US SSN
  /\b\d{3}-\d{2}-\d{4}\b/g,
  // Long opaque key material
  /\b[A-Za-z0-9_-]{32,}\b/g,
];

const MAX_REDACT_DEPTH = 8;

/** True when a field name marks its value as secret or raw model content. */
export function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEY.test(key);
}

/** Apply value-pattern redaction to free text. */
export function redactText(
  input: string,
  patterns: readonly RegExp[] = DEFAULT_REDACT_PATTERNS,
): string {
  let redacted = input;
  for (const pattern of patterns) {
    redacted = redacted.replace(pattern, REDACTED);
  }
  return redacted;
}

/**
 * Observability facade over the OTel API.
 *
 * - Spans carry redacted attributes; logs emitted inside a span carry its trace/span id.
 * - Metric instruments are created once per name and reused.
 * - With exporterIsolation, any tracer, meter, sink or database failure is swallowed so
 *   telemetry can never fail the operation being observed.
 */
export class Observability {
  private readonly tracer: Tracer;
  private readonly meter: Meter;
  private readonly database?: Pool;
  private readonly redactPatterns: readonly RegExp[];
  private readonly exporterIsolation: boolean;
  private readonly write: (level: LogLevel, line: string) => void;
  private readonly counters = new Map<string, Counter>();
  private readonly histograms = new Map<string, Histogram>();
  private readonly gauges = new Map<string, Gauge>();
  private readonly pendingWrites = new Set<Promise<void>>();

  constructor(config: ObservabilityConfig) {
    this.tracer = (config.tracerProvider ?? trace.getTracerProvider()).getTracer(
      config.serviceName,
      config.serviceVersion,
    );
    this.meter = (config.meterProvider ?? metrics.getMeterProvider()).getMeter(
      config.serviceName,
      config.serviceVersion,
    );
    this.database = config.database;
    this.redactPatterns = config.redactPatterns ?? DEFAULT_REDACT_PATTERNS;
    this.exporterIsolation = config.exporterIsolation ?? true;
    this.write = config.write ?? defaultWrite;
  }

  startSpan(name: string, attributes: Record<string, AttributeValue> = {}): Span {
    try {
      return this.tracer.startSpan(name, { attributes: this.redactAttributes(attributes) });
    } catch (error) {
      this.isolate("span.start", error);
      return trace.wrapSpanContext(INVALID_SPAN_CONTEXT);
    }
  }

  /**
   * Run fn inside a span. Errors from fn are recorded and rethrown; errors from the
   * tracing machinery itself are isolated.
   */
  async withSpan<T>(
    name: string,
    attributes: Record<string, AttributeValue> | undefined,
    fn: (span: Span) => Promise<T>,
  ): Promise<T> {
    const span = this.startSpan(name, attributes);
    let spanContext = context.active();
    try {
      spanContext = trace.setSpan(context.active(), span);
    } catch (error) {
      this.isolate("span.context", error);
    }

    try {
      const result = await context.with(spanContext, () => fn(span));
      this.safely("span.status", () => span.setStatus({ code: SpanStatusCode.OK }));
      return result;
    } catch (error) {
      this.safely("span.status", () => {
        span.setStatus({
          code: SpanStatusCode.ERROR,
          message: this.redactString(error instanceof Error ? error.message : String(error)),
        });
        span.recordException(
          error instanceof Error
            ? { name: error.name, message: this.redactString(error.message) }
            : { name: "unknown_error" },
        );
      });
      throw error;
    } finally {
      this.safely("span.end", () => span.end());
    }
  }

  /** Trace context of the active span, or null when there is none or it is invalid. */
  getTraceContext(): TraceContext | null {
    try {
      const spanContext = trace.getSpan(context.active())?.spanContext();
      if (!spanContext || !trace.isSpanContextValid(spanContext)) return null;
      return {
        traceId: spanContext.traceId,
        spanId: spanContext.spanId,
        traceFlags: spanContext.traceFlags,
      };
    } catch (error) {
      this.isolate("trace.context", error);
      return null;
    }
  }

  recordCounter(name: string, value: number, labels: MetricLabels = {}): void {
    this.safely("metric.counter", () => {
      let counter = this.counters.get(name);
      if (!counter) {
        counter = this.meter.createCounter(name);
        this.counters.set(name, counter);
      }
      counter.add(value, this.redactLabels(labels));
    });
  }

  recordHistogram(name: string, value: number, labels: MetricLabels = {}): void {
    this.safely("metric.histogram", () => {
      let histogram = this.histograms.get(name);
      if (!histogram) {
        histogram = this.meter.createHistogram(name);
        this.histograms.set(name, histogram);
      }
      histogram.record(value, this.redactLabels(labels));
    });
  }

  recordGauge(name: string, value: number, labels: MetricLabels = {}): void {
    this.safely("metric.gauge", () => {
      let gauge = this.gauges.get(name);
      if (!gauge) {
        gauge = this.meter.createGauge(name);
        this.gauges.set(name, gauge);
      }
      gauge.record(value, this.redactLabels(labels));
    });
  }

  log(level: LogLevel, message: string, data: Record<string, unknown> = {}): void {
    let entry: LogEntry;
    try {
      entry = {
        timestamp: new Date().toISOString(),
        level,
        message: this.redactString(message),
        data: this.redactObject(data, 0),
        trace: this.getTraceContext(),
      };
      this.write(level, JSON.stringify(entry));
    } catch (error) {
      this.isolate("log.write", error);
      return;
    }

    if (this.database && (level === "warn" || level === "error")) {
      const pending = this.persistLog(entry)
        .catch((error) => this.isolate("log.persist", error, { rethrow: false }))
        .finally(() => this.pendingWrites.delete(pending));
      this.pendingWrites.add(pending);
    }
  }

  /** Wait for in-flight log persistence (for shutdown and tests). */
  async flush(): Promise<void> {
    await Promise.all([...this.pendingWrites]);
  }

  redactString(input: string): string {
    return redactText(input, this.redactPatterns);
  }

  private redactValue(value: unknown, depth: number): unknown {
    if (typeof value === "string") return this.redactString(value);
    if (Array.isArray(value)) {
      return depth >= MAX_REDACT_DEPTH
        ? REDACTED
        : value.map((item) => this.redactValue(item, depth + 1));
    }
    if (value !== null && typeof value === "object") {
      return depth >= MAX_REDACT_DEPTH
        ? REDACTED
        : this.redactObject(value as Record<string, unknown>, depth + 1);
    }
    return value;
  }

  private redactObject(obj: Record<string, unknown>, depth: number): Record<string, unknown> {
    const redacted: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      redacted[key] = SENSITIVE_KEY.test(key) ? REDACTED : this.redactValue(value, depth);
    }
    return redacted;
  }

  private redactAttributes(attrs: Record<string, AttributeValue>): Record<string, AttributeValue> {
    const redacted: Record<string, AttributeValue> = {};
    for (const [key, value] of Object.entries(attrs)) {
      if (SENSITIVE_KEY.test(key)) redacted[key] = REDACTED;
      else redacted[key] = typeof value === "string" ? this.redactString(value) : value;
    }
    return redacted;
  }

  /** Sensitive labels are dropped, not masked, so they add no metric cardinality. */
  private redactLabels(labels: MetricLabels): Record<string, string> {
    const redacted: Record<string, string> = {};
    for (const [key, value] of Object.entries(labels)) {
      if (value === undefined || SENSITIVE_KEY.test(key)) continue;
      redacted[key] = this.redactString(value);
    }
    return redacted;
  }

  private safely(operation: string, fn: () => void): void {
    try {
      fn();
    } catch (error) {
      this.isolate(operation, error);
    }
  }

  private isolate(operation: string, error: unknown, options: { rethrow?: boolean } = {}): void {
    if (!this.exporterIsolation && options.rethrow !== false) throw error;
    try {
      process.stderr.write(
        `${JSON.stringify({
          level: "warn",
          message: "telemetry.isolated_failure",
          operation,
          error: error instanceof Error ? error.name : "unknown_error",
        })}\n`,
      );
    } catch {
      // The failure report itself must not break the caller either.
    }
  }

  private async persistLog(entry: LogEntry): Promise<void> {
    const database = this.database;
    if (!database) return;
    await database.query(
      `INSERT INTO observability_logs (timestamp, level, message, data, trace_id, span_id)
       VALUES ($1, $2, $3, $4::jsonb, $5, $6)`,
      [
        entry.timestamp,
        entry.level,
        entry.message,
        JSON.stringify(entry.data),
        entry.trace?.traceId ?? null,
        entry.trace?.spanId ?? null,
      ],
    );
  }
}

function defaultWrite(level: LogLevel, line: string): void {
  (level === "warn" || level === "error" ? process.stderr : process.stdout).write(`${line}\n`);
}
