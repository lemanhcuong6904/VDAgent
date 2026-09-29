CREATE TABLE IF NOT EXISTS web_events (
  id bigserial PRIMARY KEY,
  user_id text NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
  event text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS web_events_user_cursor_idx
  ON web_events (user_id, id);
