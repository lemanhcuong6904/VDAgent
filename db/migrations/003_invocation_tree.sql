ALTER TABLE web_invocations
  ADD COLUMN parent_id text REFERENCES web_invocations(id);

ALTER TABLE web_invocations
  ADD COLUMN tool_call_id text;

CREATE INDEX web_invocations_parent_idx ON web_invocations (parent_id);
