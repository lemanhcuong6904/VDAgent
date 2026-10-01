-- M11.3: Immutable terminal receipt, identical replay no-op, changed replay conflict
-- Terminal receipts capture the final state of a completed run

CREATE TABLE IF NOT EXISTS terminal_receipts (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  run_id text NOT NULL,
  attempt_id text NOT NULL,

  -- Run outcome
  status text NOT NULL CHECK (status IN ('success', 'failure', 'timeout', 'cancelled')),
  exit_code integer,

  -- Input fingerprint (for replay detection)
  input_hash text NOT NULL,

  -- Output fingerprint
  output_hash text,
  artifact_ids jsonb NOT NULL DEFAULT '[]',

  -- Evidence summary
  evidence_count integer NOT NULL DEFAULT 0,
  verified_evidence_count integer NOT NULL DEFAULT 0,

  -- Resource usage
  duration_ms bigint,
  tokens_input integer,
  tokens_output integer,

  -- Immutability
  sealed_at timestamptz NOT NULL DEFAULT now(),

  -- Metadata
  metadata jsonb NOT NULL DEFAULT '{}',

  UNIQUE (run_id, attempt_id)
);

CREATE INDEX IF NOT EXISTS terminal_receipts_workspace_idx ON terminal_receipts (workspace_id, sealed_at DESC);
CREATE INDEX IF NOT EXISTS terminal_receipts_run_idx ON terminal_receipts (run_id);
CREATE INDEX IF NOT EXISTS terminal_receipts_input_idx ON terminal_receipts (input_hash, workspace_id);
CREATE INDEX IF NOT EXISTS terminal_receipts_status_idx ON terminal_receipts (status, workspace_id);
