-- M11.4: OTel traces/metrics/logs with redaction, correlation and exporter-failure isolation
-- Observability logs for audit and error tracking

CREATE TABLE IF NOT EXISTS observability_logs (
  id bigserial PRIMARY KEY,
  timestamp timestamptz NOT NULL,
  level text NOT NULL CHECK (level IN ('debug', 'info', 'warn', 'error')),
  message text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}',

  -- Trace correlation
  trace_id text,
  span_id text,

  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS observability_logs_timestamp_idx ON observability_logs (timestamp DESC);
CREATE INDEX IF NOT EXISTS observability_logs_level_idx ON observability_logs (level, timestamp DESC);
CREATE INDEX IF NOT EXISTS observability_logs_trace_idx ON observability_logs (trace_id) WHERE trace_id IS NOT NULL;
