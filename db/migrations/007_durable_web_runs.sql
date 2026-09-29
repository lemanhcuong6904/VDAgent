ALTER TABLE platform_runs
  ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;

ALTER TABLE platform_runs
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 3;

ALTER TABLE web_tasks
  ADD COLUMN IF NOT EXISTS platform_run_id text REFERENCES platform_runs(id);

CREATE UNIQUE INDEX IF NOT EXISTS web_tasks_platform_run_idx
  ON web_tasks (platform_run_id)
  WHERE platform_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS platform_runs_cancel_idx
  ON platform_runs (cancel_requested, status, updated_at);
