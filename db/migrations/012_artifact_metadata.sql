-- M11.1: Metadata-first artifact publication
-- SHA-256/length readback, owner/isolation/version tracking

CREATE TABLE IF NOT EXISTS artifacts (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  owner_run_id text NOT NULL,
  kind text NOT NULL,
  version text NOT NULL DEFAULT '1.0.0',
  status text NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
  sha256 text,
  bytes bigint,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  ready_at timestamptz
);

CREATE INDEX IF NOT EXISTS artifacts_workspace_idx ON artifacts (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS artifacts_owner_idx ON artifacts (owner_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS artifacts_kind_idx ON artifacts (kind, status);
CREATE INDEX IF NOT EXISTS artifacts_sha256_idx ON artifacts (sha256) WHERE sha256 IS NOT NULL;

-- Artifact content storage (separate table for large binary data)
CREATE TABLE IF NOT EXISTS artifact_contents (
  artifact_id text PRIMARY KEY REFERENCES artifacts(id) ON DELETE CASCADE,
  content bytea NOT NULL,
  stored_at timestamptz NOT NULL DEFAULT now()
);
