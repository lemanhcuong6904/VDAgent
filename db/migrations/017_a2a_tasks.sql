-- M12.5: A2A gateway task mapping
-- One row per external A2A task. The client id is the tenant key: an A2A caller only
-- ever sees rows it created, and user/space come from server-side client config.

CREATE TABLE IF NOT EXISTS a2a_tasks (
  id text PRIMARY KEY,
  client_id text NOT NULL,
  context_id text NOT NULL,
  message_id text NOT NULL,
  skill_id text NOT NULL,
  -- sha256 of the accepted parts; a reused messageId with other content is refused.
  content_hash text NOT NULL,
  space_id text NOT NULL,
  user_id text NOT NULL,
  web_task_id text NOT NULL REFERENCES web_tasks(id),
  run_id text NOT NULL REFERENCES platform_runs(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- A retried SendMessage with the same messageId returns the same task.
  UNIQUE (client_id, message_id)
);

CREATE INDEX IF NOT EXISTS a2a_tasks_client_idx ON a2a_tasks (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS a2a_tasks_context_idx ON a2a_tasks (client_id, context_id);
