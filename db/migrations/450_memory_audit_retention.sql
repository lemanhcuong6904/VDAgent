-- Durable audit trail for host MemoryPort mutations.
-- expires_at is explicit so retention remains enforceable even when no worker is running.
CREATE TABLE IF NOT EXISTS memory_audit_events (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  operation text NOT NULL CHECK (operation IN ('commit', 'edit', 'delete', 'revoke', 'export', 'import')),
  actor text NOT NULL,
  resource text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  success boolean NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS memory_audit_scope_idx
  ON memory_audit_events (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS memory_audit_expiry_idx
  ON memory_audit_events (expires_at);

ALTER TABLE agent_memory_entries
  ADD COLUMN IF NOT EXISTS expires_at timestamptz;

CREATE INDEX IF NOT EXISTS agent_memory_expiry_idx
  ON agent_memory_entries (expires_at)
  WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS agent_memory_legacy_retention_idx
  ON agent_memory_entries (updated_at, id)
  WHERE expires_at IS NULL;
