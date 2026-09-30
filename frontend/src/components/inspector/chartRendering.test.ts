import { describe, expect, it } from "vitest";
import { chartRenderDependencies, renderableChartSpec, rendererForSpec } from "./chartRendering";

describe("chart rendering selection", () => {
  it("prefers the Plotly projection when the chart_spec payload provides one", () => {
    const chart = {
      spec: { "$schema": "https://vega.github.io/schema/vega-lite/v6.json" },
      plotly: { renderer: "plotly", data: [], layout: { title: "DOM" }, config: { responsive: true } },
    };

    expect(renderableChartSpec(chart)).toBe(chart.plotly);
    expect(rendererForSpec(renderableChartSpec(chart))).toBe("plotly");
    expect(chartRenderDependencies(renderableChartSpec(chart))).toEqual([
      "mathjax/es5/tex-svg.js",
      "plotly.js-dist-min",
    ]);
  });

  it("falls back to Vega-Lite when no Plotly projection exists", () => {
    const chart = { spec: { "$schema": "https://vega.github.io/schema/vega-lite/v6.json" } };

    expect(renderableChartSpec(chart)).toBe(chart.spec);
    expect(rendererForSpec(renderableChartSpec(chart))).toBe("vega");
  });
});
