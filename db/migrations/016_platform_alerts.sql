-- M11.6: Alerts for stale leases, outbox lag, unknown events, cost, artifact mismatch, PII leak

CREATE TABLE IF NOT EXISTS platform_alerts (
  id bigserial PRIMARY KEY,
  fingerprint text NOT NULL,
  signal text NOT NULL CHECK (signal IN (
    'stale_leases', 'outbox_lag', 'unknown_events', 'cost_budget', 'artifact_mismatch', 'pii_leak'
  )),
  severity text NOT NULL CHECK (severity IN ('warning', 'critical')),
  title text NOT NULL,
  summary text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  runbook text NOT NULL,
  occurrences integer NOT NULL DEFAULT 1,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

-- One open row per firing condition; a repeat observation bumps occurrences instead of duplicating.
CREATE UNIQUE INDEX IF NOT EXISTS platform_alerts_open_idx
  ON platform_alerts (fingerprint) WHERE resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS platform_alerts_recent_idx
  ON platform_alerts (last_seen_at DESC);

CREATE INDEX IF NOT EXISTS platform_alerts_signal_idx
  ON platform_alerts (signal, severity);
