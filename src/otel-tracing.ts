/**
 * OTLP tracing bootstrap.
 *
 * Exports spans over OTLP/HTTP to any collector, including Langfuse (set
 * LANGFUSE_HOST + keys, or point OTEL_EXPORTER_OTLP_ENDPOINT at a collector).
 * Langfuse reads the OpenTelemetry GenAI semantic conventions, so `agent.model`
 * spans carry gen_ai.* attributes written by PiRuntime.
 *
 * Nothing here is required: with no exporter configured the platform keeps using
 * JSON telemetry and this module is never instantiated.
 */

import { type Context, context, SpanStatusCode, trace } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  type BasicTracerProvider,
  BatchSpanProcessor,
  NodeTracerProvider,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
} from "@opentelemetry/sdk-trace-node";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";
import {
  newTraceContext,
  type SpanHandle,
  type Telemetry,
  type TraceContext,
} from "./observability.js";

export interface TracingExport {
  endpoint: string;
  headers: Record<string, string>;
  serviceName: string;
  serviceVersion: string;
  /** Sample ratio in (0, 1]; 1 exports every trace. */
  sampleRatio: number;
}

const LANGFUSE_OTLP_PATH = "/api/public/otel";

/**
 * Resolve exporter settings from the environment, or undefined when tracing is off.
 *
 * Precedence: explicit OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, then LANGFUSE_HOST
 * (with basic auth built from the key pair), then OTEL_EXPORTER_OTLP_ENDPOINT.
 */
export function resolveTracingExport(
  env: NodeJS.ProcessEnv = process.env,
): TracingExport | undefined {
  const headers = parseHeaders(env.OTEL_EXPORTER_OTLP_HEADERS);
  let endpoint = env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT?.trim();

  if (!endpoint) {
    const langfuseHost = env.LANGFUSE_HOST?.trim();
    const publicKey = env.LANGFUSE_PUBLIC_KEY?.trim();
    const secretKey = env.LANGFUSE_SECRET_KEY?.trim();
    if (langfuseHost) {
      if (!publicKey || !secretKey) {
        throw new Error("LANGFUSE_HOST needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY");
      }
      endpoint = `${langfuseHost.replace(/\/+$/, "")}${LANGFUSE_OTLP_PATH}/v1/traces`;
      // Langfuse authenticates the OTel endpoint with the project key pair.
      headers.Authorization = `Basic ${Buffer.from(`${publicKey}:${secretKey}`).toString("base64")}`;
    }
  }

  if (!endpoint) {
    const base = env.OTEL_EXPORTER_OTLP_ENDPOINT?.trim();
    if (base) endpoint = `${base.replace(/\/+$/, "")}/v1/traces`;
  }

  if (!endpoint) return undefined;

  return {
    endpoint,
    headers,
    serviceName: env.OTEL_SERVICE_NAME?.trim() || "team6-cai",
    serviceVersion: env.OTEL_SERVICE_VERSION?.trim() || "0.0.0",
    sampleRatio: sampleRatio(env.OTEL_TRACES_SAMPLER_ARG),
  };
}

function sampleRatio(raw: string | undefined): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 1) return 1;
  return parsed;
}

/** Parse the W3C `key=value,key2=value2` header form used by the OTEL_ env vars. */
function parseHeaders(raw: string | undefined): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const pair of (raw ?? "").split(",")) {
    const index = pair.indexOf("=");
    if (index <= 0) continue;
    const key = pair.slice(0, index).trim();
    const value = pair.slice(index + 1).trim();
    if (key && value) headers[key] = value;
  }
  return headers;
}

export interface Tracing {
  telemetry: Telemetry;
  /** Flush pending spans and stop the exporter. Never throws. */
  shutdown(): Promise<void>;
}

/**
 * Register a global tracer provider exporting to `settings` and return a Telemetry
 * that writes OTel spans. Returns undefined when tracing is not configured.
 */
export function startTracing(
  settings: TracingExport | undefined = resolveTracingExport(),
): Tracing | undefined {
  if (!settings) return undefined;

  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: settings.serviceName,
      [ATTR_SERVICE_VERSION]: settings.serviceVersion,
    }),
    sampler: new ParentBasedSampler({
      root: new TraceIdRatioBasedSampler(settings.sampleRatio),
    }),
    spanProcessors: [
      new BatchSpanProcessor(
        new OTLPTraceExporter({ url: settings.endpoint, headers: settings.headers }),
      ),
    ],
  });
  provider.register();
  return {
    telemetry: new OtelTelemetry(provider, settings.serviceName, settings.serviceVersion),
    shutdown: () => provider.shutdown().catch(() => undefined),
  };
}

/**
 * Telemetry backed by the OTel API.
 *
 * The platform passes its own TraceContext (UUIDs) between components, so this
 * keeps a map from those ids to the OTel Context of the span that owns them. A
 * child span started with its parent's TraceContext nests correctly; one started
 * with an unknown context becomes a new root.
 */
export class OtelTelemetry implements Telemetry {
  private readonly contexts = new Map<string, Context>();

  constructor(
    provider: BasicTracerProvider,
    serviceName: string,
    serviceVersion: string,
    private readonly tracer = provider.getTracer(serviceName, serviceVersion),
  ) {}

  startSpan(
    name: string,
    parent?: TraceContext,
    attributes: Record<string, string | number | boolean> = {},
  ): SpanHandle {
    const spanContext = newTraceContext(parent);
    const parentContext = parent ? this.contexts.get(parent.spanId) : undefined;
    const span = this.tracer.startSpan(name, { attributes }, parentContext ?? context.active());
    const active = trace.setSpan(parentContext ?? context.active(), span);
    this.contexts.set(spanContext.spanId, active);

    let status: "ok" | "error" = "ok";
    return {
      context: spanContext,
      setAttribute: (key, value) => span.setAttribute(key, value),
      recordException: (error) => {
        status = "error";
        span.recordException(error instanceof Error ? error : { name: "unknown_error" });
      },
      end: (result) => {
        if (result) status = result;
        span.setStatus({ code: status === "ok" ? SpanStatusCode.OK : SpanStatusCode.ERROR });
        span.end();
        this.contexts.delete(spanContext.spanId);
      },
    };
  }

  count(): void {
    // Metrics stay on the Prometheus path; only traces are exported over OTLP.
  }

  observe(): void {}
}
