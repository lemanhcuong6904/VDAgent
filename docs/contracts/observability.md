# Observability - M11.4

**Status**: ✅ Completed
**Purpose**: OTel traces/metrics/logs with redaction, correlation and exporter-failure isolation

## Overview

`src/otel-observability.ts` exposes an `Observability` facade over the OpenTelemetry API
(`@opentelemetry/api` 1.9.1). It produces spans, metrics and structured JSON logs; every
attribute, label and log payload is redacted before it leaves the process, logs are stamped
with the active trace/span id, and telemetry failures can never fail the observed operation.

The legacy `src/observability.ts` (`Telemetry`, `JsonLogger`, `newTraceContext`) is unchanged
and still used by the server, runtime and tool pool.

## API

```typescript
const observability = new Observability({
  serviceName: "agent-platform",
  serviceVersion: "1.0.0",
  tracerProvider,          // optional, defaults to the global OTel provider
  meterProvider,           // optional, defaults to the global OTel provider
  database: pool,          // optional, persists warn/error logs
  redactPatterns,          // optional, replaces the default value patterns
  exporterIsolation: true, // default
  write,                   // optional log sink (level, jsonLine)
});

await observability.withSpan("run.execute", { workspace_id, run_id }, async (span) => {
  observability.log("info", "step started", { step_id });
  observability.recordHistogram("run.duration_ms", 1200, { agent_type: "analytics" });
});

observability.recordCounter("runs.completed", 1, { workspace_id, status: "success" });
observability.recordGauge("outbox.lag", 4, { workspace_id });
observability.getTraceContext(); // { traceId, spanId, traceFlags } | null
await observability.flush();     // wait for pending log persistence
```

| Method | Behaviour |
| --- | --- |
| `startSpan(name, attrs)` | Span with redacted attributes; non-recording no-op span if the tracer fails |
| `withSpan(name, attrs, fn)` | Runs `fn` in the span's context; `OK` on success; on error sets `ERROR` with a redacted message, records a redacted exception and rethrows the original error |
| `getTraceContext()` | Active span context, `null` outside a span or when the context is invalid |
| `recordCounter/Histogram/Gauge` | One instrument per name, created lazily and reused |
| `log(level, message, data)` | Redacted JSON line (`timestamp, level, message, data, trace`); `warn`/`error` go to stderr by default |
| `redactString(input)` | Applies the value patterns to free text |

## Redaction

- **Sensitive keys** (`password`, `secret`, `token`, `api_key`, `credential`, `authorization`,
  `private_key`, `ssn`, `credit_card`, `prompt`, `model_input`, `model_output`, `cookie`,
  `session_key`) are replaced with `[REDACTED]` in log data and span attributes, at any depth.
  Raw prompts and model payloads are never emitted.
- **Metric labels** with sensitive keys are dropped rather than masked, so they add no
  cardinality.
- **Value patterns** in any string: inline `key=value` secrets, Bearer tokens, AWS access key
  ids, emails, credit card numbers, US SSNs and opaque tokens of 32+ characters.
- Recursion stops at depth 8; anything deeper becomes `[REDACTED]`.
- Ordinary identifiers (`run_42`, `ws_prod`) are left intact.

## Correlation

Spans nest through the active OTel context, so a child span shares its parent's trace id.
Logs emitted inside a span carry `trace.traceId`/`trace.spanId`; outside a span `trace` is
`null`. Propagation across `await` requires a context manager such as
`AsyncLocalStorageContextManager`, which the OTel Node SDK registers by default.

## Exporter-failure isolation

With `exporterIsolation: true`, failures from the tracer, meter, log sink or database are
caught. The caller's operation still runs and returns normally, and one line is written to
stderr:

```json
{"level":"warn","message":"telemetry.isolated_failure","operation":"span.start","error":"Error"}
```

Only the error name is reported, never its message, so a failing exporter cannot leak data.
With `exporterIsolation: false` failures propagate (useful in tests), except log persistence,
which is always isolated.

## Log persistence

When `database` is set, `warn` and `error` entries are written asynchronously to
`observability_logs` (migration `015_observability_logs`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `bigserial` | Primary key |
| `timestamp` | `timestamptz` | Entry time |
| `level` | `text` | `debug`/`info`/`warn`/`error` |
| `message` | `text` | Redacted |
| `data` | `jsonb` | Redacted |
| `trace_id`, `span_id` | `text` | `NULL` outside a span |
| `created_at` | `timestamptz` | Insert time |

Indexes: `timestamp`, `level`, `trace_id` (partial, non-null).

## Deployment note

The application does not register an OTel SDK or exporter yet. Without one, the global
providers are no-ops: spans and metrics are dropped while logs still go to the sink and the
database. To export, register an SDK (for example `@opentelemetry/sdk-node` with an OTLP
exporter) before constructing `Observability`, or inject providers explicitly.

## Testing

```bash
# Unit tests (in-memory span exporter and metric reader, no database)
npx vitest run test/otel-observability.test.ts

# Including the PostgreSQL persistence test
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db npx vitest run test/otel-observability.test.ts
```

Coverage: attribute redaction, OK/ERROR status, redacted exceptions, span nesting, log
correlation, counter/histogram/gauge values, label dropping, key and pattern redaction,
depth bound, tracer/meter/sink/database failure isolation, strict mode, and redacted,
correlated rows in `observability_logs`.
