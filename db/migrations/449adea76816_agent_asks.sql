-- revision: 449adea76816_agent_asks
-- down_revision: 017_a2a_tasks

-- M6: durable peer-to-peer agent ask/answer with wait-for cycle detection.
-- web_invocations only models a strict parent->child tree (parent_id), so a
-- sibling agent has no way to block on another sibling. This adds that
-- capability without touching the existing tree structure.

-- One row per outstanding or resolved "ask": agent A blocks on agent B
-- within the same task, waiting for an answer keyed by questionId.
CREATE TABLE IF NOT EXISTS web_agent_asks (
  id text PRIMARY KEY,
  task_id text NOT NULL,
  user_id text NOT NULL,
  space_id text NOT NULL,
  question_id text NOT NULL,
  from_agent text NOT NULL,
  to_agent text NOT NULL,
  content jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered', 'cancelled')),
  answer jsonb,
  answer_status text CHECK (answer_status IN ('success', 'error', 'timeout')),
  created_at timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  UNIQUE (task_id, question_id)
);

CREATE INDEX IF NOT EXISTS web_agent_asks_pending_idx
  ON web_agent_asks (task_id, to_agent) WHERE status = 'pending';

-- Wait-for edges backing cycle detection: while ask A is pending, A is
-- "waiting on" B. A new ask is rejected if it would close a cycle in this
-- graph, mirroring InMemoryMailbox.wouldCreateCycle but durable and scoped
-- per task so unrelated tasks can never interact.
CREATE TABLE IF NOT EXISTS web_wait_for_edges (
  task_id text NOT NULL,
  question_id text NOT NULL,
  waiting_agent text NOT NULL,
  blocked_on_agent text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, question_id)
);

CREATE INDEX IF NOT EXISTS web_wait_for_edges_task_idx ON web_wait_for_edges (task_id);
