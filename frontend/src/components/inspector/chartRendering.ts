import type { ChartSpecDTO } from "../../api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function renderableChartSpec(chart: Pick<ChartSpecDTO, "spec" | "plotly">): Record<string, unknown> {
  return isRecord(chart.plotly) ? chart.plotly : chart.spec;
}

export function rendererForSpec(spec: Record<string, unknown>): "plotly" | "vega" {
  return spec.renderer === "plotly" ? "plotly" : "vega";
}

export function chartRenderDependencies(spec: Record<string, unknown>): string[] {
  return rendererForSpec(spec) === "plotly" ? ["mathjax/es5/tex-svg.js", "plotly.js-dist-min"] : ["vega-embed"];
}

export function plotlyParts(spec: Record<string, unknown>) {
  return {
    data: Array.isArray(spec.data) ? spec.data : [],
    layout: isRecord(spec.layout) ? spec.layout : {},
    config: isRecord(spec.config) ? spec.config : {},
  };
}
