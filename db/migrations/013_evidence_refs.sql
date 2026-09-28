-- M11.2: Evidence refs linking source/run/tool/model/artifact revision
-- Missing evidence = unavailable verification

CREATE TABLE IF NOT EXISTS evidence_refs (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  run_id text NOT NULL,
  attempt_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('source', 'tool_call', 'model_call', 'artifact_ref', 'checkpoint')),
  verification text NOT NULL CHECK (verification IN ('unverified', 'verified', 'unavailable')),

  -- Source evidence
  source_type text,
  source_location text,
  source_revision text,

  -- Tool call evidence
  tool_id text,
  tool_input_hash text,
  tool_output_hash text,

  -- Model call evidence
  model_id text,
  model_input_hash text,
  model_output_hash text,
  model_tokens jsonb,

  -- Artifact reference evidence
  artifact_id text,
  artifact_sha256 text,

  -- Checkpoint evidence
  checkpoint_id text,
  checkpoint_revision integer,

  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz
);

CREATE INDEX IF NOT EXISTS evidence_refs_workspace_idx ON evidence_refs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS evidence_refs_run_idx ON evidence_refs (run_id, created_at ASC);
CREATE INDEX IF NOT EXISTS evidence_refs_artifact_idx ON evidence_refs (artifact_id) WHERE artifact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS evidence_refs_verification_idx ON evidence_refs (verification, kind);
