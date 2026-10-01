CREATE TABLE agent_memory_entries (
  id text PRIMARY KEY,
  space_id text NOT NULL,
  user_id text NOT NULL,
  agent_id text NOT NULL,
  text text NOT NULL,
  tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_memory_scope_created_idx
  ON agent_memory_entries (space_id, user_id, agent_id, created_at, id);

CREATE TABLE pi_sessions (
  space_id text NOT NULL,
  user_id text NOT NULL,
  agent_id text NOT NULL,
  session_id text NOT NULL,
  messages jsonb NOT NULL CHECK (jsonb_typeof(messages) = 'array'),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (space_id, user_id, agent_id, session_id)
);
