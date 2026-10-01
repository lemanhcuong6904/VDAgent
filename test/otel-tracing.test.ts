import { describe, expect, it } from "vitest";
import { resolveTracingExport } from "../src/otel-tracing.js";

describe("resolveTracingExport", () => {
  it("returns undefined with no OTLP or Langfuse settings", () => {
    expect(resolveTracingExport({})).toBeUndefined();
  });

  it("prefers an explicit traces endpoint", () => {
    const settings = resolveTracingExport({
      OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: "http://collector:4318/v1/traces",
      OTEL_SERVICE_NAME: "team6-cai-test",
    });
    expect(settings).toEqual({
      endpoint: "http://collector:4318/v1/traces",
      headers: {},
      serviceName: "team6-cai-test",
      serviceVersion: "0.0.0",
      sampleRatio: 1,
    });
  });

  it("derives the Langfuse OTLP endpoint and basic-auth header from the key pair", () => {
    const settings = resolveTracingExport({
      LANGFUSE_HOST: "https://cloud.langfuse.com/",
      LANGFUSE_PUBLIC_KEY: "pk-test",
      LANGFUSE_SECRET_KEY: "sk-test",
    });
    expect(settings?.endpoint).toBe("https://cloud.langfuse.com/api/public/otel/v1/traces");
    expect(settings?.headers.Authorization).toBe(
      `Basic ${Buffer.from("pk-test:sk-test").toString("base64")}`,
    );
  });

  it("rejects a Langfuse host without both keys", () => {
    expect(() => resolveTracingExport({ LANGFUSE_HOST: "https://cloud.langfuse.com" })).toThrow(
      /LANGFUSE_PUBLIC_KEY/,
    );
  });

  it("falls back to a generic OTLP base endpoint", () => {
    const settings = resolveTracingExport({ OTEL_EXPORTER_OTLP_ENDPOINT: "http://collector:4318" });
    expect(settings?.endpoint).toBe("http://collector:4318/v1/traces");
  });

  it("clamps an invalid sample ratio back to 1", () => {
    const settings = resolveTracingExport({
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://collector:4318",
      OTEL_TRACES_SAMPLER_ARG: "not-a-number",
    });
    expect(settings?.sampleRatio).toBe(1);
  });

  it("parses custom OTLP headers", () => {
    const settings = resolveTracingExport({
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://collector:4318",
      OTEL_EXPORTER_OTLP_HEADERS: "x-api-key=abc,x-team=six",
    });
    expect(settings?.headers).toEqual({ "x-api-key": "abc", "x-team": "six" });
  });
});
