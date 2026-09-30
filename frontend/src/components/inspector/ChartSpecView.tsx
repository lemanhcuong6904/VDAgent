import { useEffect, useRef, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import { useChartSpec } from "../../api/queries";

/** A version-pinned shared Artifact Store chart_spec rendered from its Vega-Lite payload. */
export function ChartSpecView({ id, version }: { id: string; version: number }) {
  const query = useChartSpec(id, version);
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const spec = query.data?.spec;

  useEffect(() => {
    const el = container.current;
    if (!el || !spec) return;
    let disposed = false;
    let finalize: (() => void) | undefined;
    setError(null);
    import("vega-embed")
      .then(({ default: embed }) =>
        embed(el, { ...spec, width: "container", autosize: { type: "fit-x", contains: "padding" } } as VisualizationSpec, {
          actions: false,
          renderer: "svg",
        }),
      )
      .then((result) => {
        if (disposed) result.finalize();
        else finalize = () => result.finalize();
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      disposed = true;
      finalize?.();
    };
  }, [spec]);

  const label = `${id}@${version}`;
  if (query.isPending) return <div className="muted small">Loading {label}…</div>;
  if (query.isError) return <div className="error-text">{label}: {query.error.message}</div>;
  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="mono artifact-id">{label}</span>
        <span className="chart-title">{query.data.title}</span>
      </figcaption>
      <div className="chart-canvas" ref={container} />
      {error && <div className="error-text">Chart failed to render: {error}</div>}
    </figure>
  );
}
