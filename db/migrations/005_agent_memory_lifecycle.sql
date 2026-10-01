ALTER TABLE agent_memory_entries
  ADD COLUMN IF NOT EXISTS memory_key text,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS agent_memory_key_scope_idx
  ON agent_memory_entries (space_id, user_id, agent_id, memory_key);
