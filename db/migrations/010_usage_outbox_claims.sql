ALTER TABLE platform_outbox_events
  ADD COLUMN IF NOT EXISTS claimed_by text,
  ADD COLUMN IF NOT EXISTS claimed_until timestamptz,
  ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error text;

CREATE INDEX IF NOT EXISTS platform_outbox_claim_idx
  ON platform_outbox_events (claimed_until, id)
  WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS platform_usage_records (
  id bigserial PRIMARY KEY,
  run_id text REFERENCES platform_runs(id) ON DELETE CASCADE,
  user_id text NOT NULL,
  space_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('model', 'tool', 'sandbox', 'worker')),
  provider text,
  model text,
  agent_id text,
  tool_name text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  estimated_cost numeric(20, 8),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS platform_usage_records_scope_idx
  ON platform_usage_records (space_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS platform_usage_records_run_idx
  ON platform_usage_records (run_id, created_at);
