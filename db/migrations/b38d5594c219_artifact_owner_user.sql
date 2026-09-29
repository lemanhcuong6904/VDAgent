-- revision: b38d5594c219_artifact_owner_user
-- down_revision: 450_memory_audit_retention

-- Bind private artifacts to the user that created their owning run. Workspace ids
-- are not an authorization grant: several users may share a workspace.
ALTER TABLE artifacts
  ADD COLUMN IF NOT EXISTS owner_user_id text;

UPDATE artifacts a
SET owner_user_id = COALESCE(
  (SELECT r.user_id FROM platform_runs r WHERE r.id = a.owner_run_id),
  (SELECT i.user_id FROM web_invocations i WHERE i.id = a.owner_run_id)
)
WHERE owner_user_id IS NULL;

CREATE INDEX IF NOT EXISTS artifacts_workspace_user_idx
  ON artifacts (workspace_id, owner_user_id, created_at DESC);
