ALTER TABLE web_invocations
  ADD COLUMN IF NOT EXISTS platform_run_id text REFERENCES platform_runs(id);

CREATE UNIQUE INDEX IF NOT EXISTS web_invocations_platform_run_idx
  ON web_invocations (platform_run_id)
  WHERE platform_run_id IS NOT NULL;

-- A tool call is the idempotency boundary for an A2A send. Retrying the same
-- host call must not enqueue a second child invocation.
CREATE UNIQUE INDEX IF NOT EXISTS web_invocations_parent_tool_call_idx
  ON web_invocations (parent_id, tool_call_id)
  WHERE parent_id IS NOT NULL AND tool_call_id IS NOT NULL;
