CREATE TABLE platform_runs (
  id text PRIMARY KEY,
  space_id text NOT NULL,
  user_id text NOT NULL,
  workflow_id text NOT NULL,
  workflow_version text NOT NULL,
  status text NOT NULL CHECK (status IN ('queued', 'leased', 'running', 'waiting', 'retryable', 'completed', 'failed', 'cancelled')),
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  output jsonb,
  error text,
  idempotency_key text NOT NULL,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  worker_id text,
  lease_until timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  deadline_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (space_id, user_id, idempotency_key)
);
CREATE INDEX platform_runs_claim_idx
  ON platform_runs (status, lease_until, created_at);
CREATE INDEX platform_runs_scope_idx
  ON platform_runs (space_id, user_id, created_at DESC);

CREATE TABLE platform_run_steps (
  id text PRIMARY KEY,
  run_id text NOT NULL REFERENCES platform_runs(id) ON DELETE CASCADE,
  parent_step_id text REFERENCES platform_run_steps(id),
  kind text NOT NULL CHECK (kind IN ('planner', 'agent', 'tool', 'approval')),
  agent_id text,
  capability text,
  status text NOT NULL CHECK (status IN ('queued', 'running', 'waiting', 'completed', 'failed', 'cancelled')),
  input jsonb,
  output jsonb,
  error text,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);
CREATE INDEX platform_run_steps_run_idx ON platform_run_steps (run_id, created_at);

CREATE TABLE platform_run_events (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES platform_runs(id) ON DELETE CASCADE,
  space_id text NOT NULL,
  user_id text NOT NULL,
  seq bigint NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, seq)
);
CREATE INDEX platform_run_events_cursor_idx ON platform_run_events (run_id, seq);

CREATE TABLE platform_outbox_events (
  id bigserial PRIMARY KEY,
  run_id text REFERENCES platform_runs(id) ON DELETE CASCADE,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX platform_outbox_pending_idx
  ON platform_outbox_events (id) WHERE published_at IS NULL;

CREATE TABLE platform_worker_leases (
  run_id text PRIMARY KEY REFERENCES platform_runs(id) ON DELETE CASCADE,
  worker_id text NOT NULL,
  fencing_token bigint NOT NULL,
  lease_until timestamptz NOT NULL,
  heartbeat_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform_idempotency_keys (
  space_id text NOT NULL,
  user_id text NOT NULL,
  idempotency_key text NOT NULL,
  run_id text NOT NULL REFERENCES platform_runs(id) ON DELETE CASCADE,
  response jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (space_id, user_id, idempotency_key)
);
