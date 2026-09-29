CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,               -- 'u_…'
  name        TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,               -- 't_…'
  user_id     TEXT NOT NULL REFERENCES users(id),
  root_agent  TEXT NOT NULL,                  -- agent whose chat the human posted in
  status      TEXT NOT NULL CHECK (status IN ('running','completed','failed','cancelled')),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id, created_at);

CREATE TABLE IF NOT EXISTS invocations (
  id           TEXT PRIMARY KEY,              -- 'inv_…'
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  user_id      TEXT NOT NULL REFERENCES users(id),
  agent        TEXT NOT NULL,                 -- callee = stack owner
  caller       TEXT NOT NULL,                 -- 'user' or agent name
  parent_id    TEXT REFERENCES invocations(id),
  tool_call_id TEXT,                          -- parent's send_to_agent tool call id
  depth        INTEGER NOT NULL,
  inbound_text TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled','rejected')),
  result_text  TEXT,
  error        TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at   TEXT,
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_inv_task  ON invocations(task_id);
CREATE INDEX IF NOT EXISTS ix_inv_stack ON invocations(user_id, agent, status);

CREATE TABLE IF NOT EXISTS messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         TEXT NOT NULL REFERENCES users(id),
  agent           TEXT NOT NULL,              -- stack = (user_id, agent)
  seq             INTEGER NOT NULL,           -- per-stack order, starts at 1
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  invocation_id   TEXT NOT NULL REFERENCES invocations(id),
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  sender          TEXT,                       -- role=user: 'user' or agent name
  content         TEXT NOT NULL DEFAULT '',   -- raw text (no [from:] prefix)
  tool_calls_json TEXT,                       -- role=assistant: [{"id","name","arguments_json"}]
  tool_call_id    TEXT,                       -- role=tool
  compacted       INTEGER NOT NULL DEFAULT 0 CHECK (compacted IN (0,1)),
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (user_id, agent, seq)
);
CREATE INDEX IF NOT EXISTS ix_msg_task ON messages(task_id);

CREATE TABLE IF NOT EXISTS stack_summaries (
  user_id    TEXT NOT NULL REFERENCES users(id),
  agent      TEXT NOT NULL,
  summary    TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (user_id, agent)
);

CREATE TABLE IF NOT EXISTS datasets (
  id            TEXT PRIMARY KEY,             -- 'ds_…'; also its table name in query_datasets
  user_id       TEXT NOT NULL REFERENCES users(id),
  invocation_id TEXT NOT NULL REFERENCES invocations(id),
  name          TEXT,
  source_sql    TEXT NOT NULL,
  columns_json  TEXT NOT NULL,                -- [{"name","type"}]
  rows_json     TEXT NOT NULL,                -- [[…], …], ≤ 10 000 rows
  row_count     INTEGER NOT NULL,
  truncated     INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0,1)),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_ds_user ON datasets(user_id);

CREATE TABLE IF NOT EXISTS charts (
  id            TEXT PRIMARY KEY,             -- 'ch_…'
  user_id       TEXT NOT NULL REFERENCES users(id),
  invocation_id TEXT NOT NULL REFERENCES invocations(id),
  dataset_id    TEXT NOT NULL REFERENCES datasets(id),
  title         TEXT NOT NULL,
  spec_json     TEXT NOT NULL,                -- Vega-Lite v5, data inlined
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS reports (
  id            TEXT PRIMARY KEY,             -- 'rp_…'
  user_id       TEXT NOT NULL REFERENCES users(id),
  invocation_id TEXT NOT NULL REFERENCES invocations(id),
  title         TEXT NOT NULL,
  markdown      TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_rp_user ON reports(user_id, created_at);

-- Agent memory (agent-freedom spec §2): notes of one (user_id, agent) scope. The plugin decides
-- what to save; embeddings are its own (any model, any dimension; NULL = none).
CREATE TABLE IF NOT EXISTS memories (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL REFERENCES users(id),
  agent       TEXT NOT NULL,
  kind        TEXT NOT NULL,
  text        TEXT NOT NULL,
  embedding   BLOB,                           -- float32 little-endian (sqlite_vec.serialize_float32)
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_memories_scope ON memories(user_id, agent, id);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

-- Artifact Store (D5, system prompt §6.2): immutable envelopes. A correction is a new version of the same
-- artifact_id; the previous version's status becomes SUPERSEDED (the only update allowed).
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id             TEXT NOT NULL,          -- 'art_…'
  version                 INTEGER NOT NULL CHECK (version >= 1),
  run_id                  TEXT NOT NULL,
  task_id                 TEXT NOT NULL,
  user_id                 TEXT NOT NULL REFERENCES users(id),
  artifact_type           TEXT NOT NULL,
  schema_version          TEXT NOT NULL,
  status                  TEXT NOT NULL CHECK (status IN ('DRAFT','VALID','PARTIAL','INVALID','SUPERSEDED')),
  producer_json           TEXT NOT NULL,
  content_hash            TEXT NOT NULL,
  snapshot_refs_json      TEXT NOT NULL,
  semantic_config_version TEXT,
  source_refs_json        TEXT NOT NULL,
  input_refs_json         TEXT NOT NULL,
  evidence_refs_json      TEXT NOT NULL,
  limitations_json        TEXT NOT NULL,
  reason_code             TEXT,
  reason                  TEXT,
  payload_json            TEXT NOT NULL,          -- canonical JSON, Decimal as string
  created_at              TEXT NOT NULL,
  PRIMARY KEY (artifact_id, version)
);
CREATE INDEX IF NOT EXISTS ix_artifacts_run ON artifacts(user_id, run_id, artifact_type);
CREATE TRIGGER IF NOT EXISTS artifacts_immutable_update BEFORE UPDATE ON artifacts
WHEN NOT (NEW.status = 'SUPERSEDED' AND OLD.status <> 'SUPERSEDED'
          AND NEW.payload_json IS OLD.payload_json AND NEW.content_hash IS OLD.content_hash
          AND NEW.artifact_id IS OLD.artifact_id AND NEW.version IS OLD.version)
BEGIN
  SELECT RAISE(ABORT, 'artifacts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS artifacts_immutable_delete BEFORE DELETE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifacts are immutable');
END;

-- Authorized scope per user (D8): a whole project (zone_id NULL) or one zone of it.
CREATE TABLE IF NOT EXISTS user_scopes (
  user_id    TEXT NOT NULL REFERENCES users(id),
  project_id TEXT NOT NULL,
  zone_id    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_scopes ON user_scopes(user_id, project_id, IFNULL(zone_id, ''));
