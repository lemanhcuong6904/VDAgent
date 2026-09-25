CREATE INDEX IF NOT EXISTS agent_memory_search_idx
  ON agent_memory_entries
  USING GIN (to_tsvector('simple', text || ' ' || tags::text));
