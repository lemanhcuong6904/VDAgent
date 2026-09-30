declare module "plotly.js-dist-min" {
  interface PlotlyResult {
    then(onfulfilled: () => unknown): Promise<unknown>;
  }

  interface PlotlyStatic {
    newPlot(
      element: HTMLElement,
      data: unknown[],
      layout: Record<string, unknown>,
      config: Record<string, unknown>,
    ): PlotlyResult;
    purge(element: HTMLElement): void;
  }

  const plotly: PlotlyStatic;
  export default plotly;
}

declare module "mathjax/es5/tex-svg.js";
