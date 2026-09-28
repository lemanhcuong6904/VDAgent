CREATE TABLE IF NOT EXISTS platform_audit_events (
  id bigserial PRIMARY KEY,
  space_id text,
  user_id text,
  actor text NOT NULL,
  action text NOT NULL,
  resource_type text,
  resource_id text,
  outcome text NOT NULL CHECK (outcome IN ('allowed', 'denied', 'success', 'failure')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS platform_audit_scope_idx
  ON platform_audit_events (space_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS platform_audit_action_idx
  ON platform_audit_events (action, created_at DESC);
