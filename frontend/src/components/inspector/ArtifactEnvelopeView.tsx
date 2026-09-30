import { useArtifactEnvelope } from "../../api/queries";
import { ChartSpecView } from "./ChartSpecView";

function titleForPayload(payload: Record<string, unknown>, fallback: string): string {
  const title = payload.title;
  if (typeof title === "string" && title.trim()) return title;
  const claim = payload.claim;
  if (typeof claim === "string" && claim.trim()) return claim;
  const label = payload.label;
  if (typeof label === "string" && label.trim()) return label;
  return fallback;
}

export function ArtifactEnvelopeView({ id, version }: { id: string; version: number }) {
  const query = useArtifactEnvelope(id, version);
  const label = `${id}@${version}`;

  if (query.isPending) return <div className="muted small">Loading {label}...</div>;
  if (query.isError) return <div className="error-text">{label}: {query.error.message}</div>;

  const artifact = query.data;
  if (artifact.artifact_type === "chart_spec") return <ChartSpecView id={id} version={version} />;

  const heading = titleForPayload(artifact.payload, `${artifact.artifact_type} artifact`);
  return (
    <article className="envelope-view">
      <header className="envelope-view-head">
        <div>
          <div className="mono artifact-id">{label}</div>
          <h3>{heading}</h3>
        </div>
        <span className={`status-pill status-${artifact.status.toLowerCase()}`}>{artifact.status}</span>
      </header>
      <dl className="artifact-meta">
        <div>
          <dt>Type</dt>
          <dd>{artifact.artifact_type}</dd>
        </div>
        <div>
          <dt>Schema</dt>
          <dd>{artifact.schema_version}</dd>
        </div>
        <div>
          <dt>Producer</dt>
          <dd>
            {artifact.producer.agent}@{artifact.producer.agent_version}
          </dd>
        </div>
        <div>
          <dt>Snapshot</dt>
          <dd>{artifact.snapshot_refs.join(", ") || "-"}</dd>
        </div>
        <div>
          <dt>Semantic</dt>
          <dd>{artifact.semantic_config_version ?? "-"}</dd>
        </div>
      </dl>
      {artifact.limitations.length > 0 && (
        <div className="artifact-limitations">
          {artifact.limitations.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      )}
      <pre className="artifact-json">{JSON.stringify(artifact.payload, null, 2)}</pre>
    </article>
  );
}
