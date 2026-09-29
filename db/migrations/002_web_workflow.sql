CREATE TABLE IF NOT EXISTS web_users (
  id text PRIMARY KEY,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS web_tasks (
  id text PRIMARY KEY,
  user_id text NOT NULL REFERENCES web_users(id),
  root_agent text NOT NULL,
  status text NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS web_tasks_user_created_idx ON web_tasks (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS web_messages (
  id bigserial PRIMARY KEY,
  user_id text NOT NULL REFERENCES web_users(id),
  agent text NOT NULL,
  seq integer NOT NULL,
  task_id text NOT NULL REFERENCES web_tasks(id),
  invocation_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
  sender text,
  content text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, agent, seq)
);
CREATE INDEX IF NOT EXISTS web_messages_stack_idx ON web_messages (user_id, agent, seq DESC);

CREATE TABLE IF NOT EXISTS web_invocations (
  id text PRIMARY KEY,
  task_id text NOT NULL REFERENCES web_tasks(id),
  user_id text NOT NULL REFERENCES web_users(id),
  agent text NOT NULL,
  caller text NOT NULL,
  depth integer NOT NULL DEFAULT 0,
  inbound_text text NOT NULL,
  status text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'rejected')),
  result_text text,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS web_invocations_task_idx ON web_invocations (task_id, created_at);

CREATE TABLE IF NOT EXISTS web_datasets (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  invocation_id text,
  name text NOT NULL,
  columns jsonb NOT NULL,
  rows jsonb NOT NULL,
  source_sql text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_datasets_user_idx ON web_datasets (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS web_charts (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  invocation_id text,
  dataset_id text NOT NULL REFERENCES web_datasets(id),
  title text NOT NULL,
  spec jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS web_reports (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  invocation_id text,
  title text NOT NULL,
  markdown text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_reports_user_idx ON web_reports (user_id, created_at DESC);
