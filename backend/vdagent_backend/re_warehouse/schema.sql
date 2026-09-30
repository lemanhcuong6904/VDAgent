-- Real-estate DW mock (D7), table names from DW v3.1.0 as they appear in the Data, Insight and Compare specs.
-- No REAL columns: VND amounts are INTEGER, areas / percentages / ratios are decimal strings (TEXT).
-- Columns marked TODO(spec-gap) are inferred from the specs; the DW Schema v3.1.0 document wins when available.

CREATE TABLE snapshot_manifest (
  snapshot_id             TEXT PRIMARY KEY,               -- 'SNAP-2026-09-28'
  snapshot_date_key       INTEGER NOT NULL UNIQUE,        -- 20260928
  status                  TEXT NOT NULL CHECK (status IN ('APPROVED','DRAFT','REJECTED')),
  semantic_config_version TEXT NOT NULL,
  loaded_at               TEXT NOT NULL                   -- ISO-8601 UTC; freshness checks
);

CREATE TABLE semantic_config (
  config_version TEXT NOT NULL,
  config_key     TEXT NOT NULL,
  config_value   TEXT NOT NULL,                           -- JSON; decimals as JSON strings
  status         TEXT NOT NULL CHECK (status IN ('APPROVED','PENDING')),
  description    TEXT,
  PRIMARY KEY (config_version, config_key)
);

CREATE TABLE dim_project_profile (
  project_key              TEXT PRIMARY KEY,              -- 'PRJ-X'
  project_name             TEXT NOT NULL,
  market_id                TEXT NOT NULL,
  segment                  TEXT NOT NULL,                 -- TODO(spec-gap): segment values
  is_sales_permit_issued   INTEGER NOT NULL CHECK (is_sales_permit_issued IN (0,1)),
  is_bank_guarantee_issued INTEGER NOT NULL CHECK (is_bank_guarantee_issued IN (0,1))
);

CREATE TABLE dim_zone_master (
  zone_key    TEXT PRIMARY KEY,                           -- 'ZN-A'
  zone_name   TEXT NOT NULL,
  project_key TEXT NOT NULL REFERENCES dim_project_profile(project_key)
);

CREATE TABLE dim_unit_master (
  unit_key            TEXT PRIMARY KEY,                   -- 'U-PRJ-X-A12-08'
  unit_code           TEXT NOT NULL,                      -- 'A12-08'
  project_key         TEXT NOT NULL REFERENCES dim_project_profile(project_key),
  zone_key            TEXT NOT NULL REFERENCES dim_zone_master(zone_key),
  unit_type           TEXT NOT NULL,                      -- 1PN | 2PN | 3PN
  area_m2             TEXT NOT NULL,                      -- decimal string
  net_area_m2         TEXT NOT NULL,                      -- TODO(spec-gap): net vs gross
  floor_no            INTEGER NOT NULL,
  floor_band          TEXT NOT NULL CHECK (floor_band IN ('LOW','MID','HIGH','TOP')),
  balcony_orientation TEXT NOT NULL,                      -- N NE E SE S SW W NW
  view_primary_type   TEXT NOT NULL,                      -- CITY_OPEN | RIVER | INTERNAL_COURT | …
  launch_batch_id     TEXT NOT NULL,                      -- 'LB-02'
  release_date        TEXT NOT NULL,
  UNIQUE (project_key, unit_code)
);

CREATE TABLE dim_sales_channel (
  channel_key         TEXT PRIMARY KEY,
  channel_name        TEXT NOT NULL,
  base_commission_pct TEXT NOT NULL,
  spiff_bonus_vnd     INTEGER NOT NULL
);

CREATE TABLE fact_unit_inventory_snapshot (
  unit_key          TEXT NOT NULL REFERENCES dim_unit_master(unit_key),
  snapshot_date_key INTEGER NOT NULL,
  project_key       TEXT NOT NULL,
  zone_key          TEXT NOT NULL,
  channel_key       TEXT REFERENCES dim_sales_channel(channel_key),
  inventory_status  TEXT NOT NULL CHECK (inventory_status IN ('AVAILABLE','BOOKED','SOLD','LOCKED')),
  unsold_days_dom   INTEGER NOT NULL,                     -- days on market (to sale, or to snapshot if unsold)
  release_date      TEXT NOT NULL,
  snapshot_date     TEXT NOT NULL,
  sold_date         TEXT,
  asking_price_vnd  INTEGER,                              -- NULL = missing (DQ fixtures)
  net_price_per_m2  INTEGER,
  PRIMARY KEY (unit_key, snapshot_date_key)
);

CREATE TABLE fact_sales_channel_performance (
  channel_key               TEXT NOT NULL REFERENCES dim_sales_channel(channel_key),
  project_key               TEXT NOT NULL,
  snapshot_date_key         INTEGER NOT NULL,
  web_listing_views         INTEGER NOT NULL,
  locked_inventory_over_90d INTEGER NOT NULL,
  absorption_rate_pct       TEXT NOT NULL,              -- channel-level; not the semantic absorption_rate
  PRIMARY KEY (channel_key, project_key, snapshot_date_key)
);

CREATE TABLE fact_unit_price_history (
  unit_key         TEXT NOT NULL REFERENCES dim_unit_master(unit_key),
  effective_date   TEXT NOT NULL,
  asking_price_vnd INTEGER NOT NULL,
  net_price_per_m2 INTEGER NOT NULL,
  PRIMARY KEY (unit_key, effective_date)
);

CREATE TABLE fact_sales_funnel_daily (
  unit_key            TEXT NOT NULL REFERENCES dim_unit_master(unit_key),
  date_key            INTEGER NOT NULL,
  leads               INTEGER NOT NULL,
  site_visits         INTEGER NOT NULL,
  bookings            INTEGER NOT NULL,
  cancellations       INTEGER NOT NULL,
  contracts           INTEGER NOT NULL,
  cancellation_reason TEXT,                             -- free-text label; untrusted (TC-15)
  PRIMARY KEY (unit_key, date_key)
);

CREATE TABLE dim_secondary_market_comps (
  comp_key         TEXT PRIMARY KEY,
  project_key      TEXT NOT NULL,
  unit_type        TEXT NOT NULL,
  transaction_date TEXT NOT NULL,
  price_per_m2     INTEGER NOT NULL
);

CREATE TABLE fact_market_macro_monthly (
  market_id             TEXT NOT NULL,
  segment               TEXT NOT NULL,
  month_key             INTEGER NOT NULL,              -- 202609
  mortgage_rate_pct     TEXT NOT NULL,
  absorption_rate_pct   TEXT NOT NULL,
  months_of_inventory   TEXT NOT NULL,
  price_to_income_ratio TEXT NOT NULL,
  PRIMARY KEY (market_id, segment, month_key)
);

CREATE TABLE dim_infrastructure_assets (
  asset_key   TEXT PRIMARY KEY,
  project_key TEXT NOT NULL,
  asset_type  TEXT NOT NULL,                            -- METRO | SCHOOL | HOSPITAL | MALL | ROAD
  asset_name  TEXT NOT NULL,
  distance_km TEXT NOT NULL,
  status      TEXT NOT NULL                             -- OPERATING | UNDER_CONSTRUCTION | PLANNED
);

-- Diagnostic mart and cause bridge are computed by the DW pipeline (G-09), read as-is by Data/Insight.
CREATE TABLE dm_unit_friction_diagnostics (
  unit_key                    TEXT NOT NULL REFERENCES dim_unit_master(unit_key),
  snapshot_date_key           INTEGER NOT NULL,
  primary_cause_code          TEXT,                     -- NULL when the unit is not diagnosed
  price_spread_vs_peer_pct    TEXT,
  is_peer_sample_constrained  INTEGER NOT NULL DEFAULT 0 CHECK (is_peer_sample_constrained IN (0,1)),
  peer_n                      INTEGER,                  -- TODO(spec-gap)
  physical_defect_penalty     INTEGER,                  -- 0..100
  thermal_view_penalty        INTEGER,                  -- 0..100
  subsidy_duration_mo         INTEGER,
  secondary_price_gap_pct     TEXT,
  ticket_size_vs_income_ratio TEXT,
  funnel_dropoff_rate_pct     TEXT,
  west_facing_exposure_pct    TEXT,
  recommended_action          TEXT,
  PRIMARY KEY (unit_key, snapshot_date_key)
);

CREATE TABLE unit_diagnostic_causes (
  unit_key          TEXT NOT NULL REFERENCES dim_unit_master(unit_key),
  snapshot_date_key INTEGER NOT NULL,
  cause_code        TEXT NOT NULL,
  severity_rank     INTEGER NOT NULL CHECK (severity_rank >= 1),
  attribution_score TEXT NOT NULL,                      -- decimal string, per unit sums to 1.000
  PRIMARY KEY (unit_key, snapshot_date_key, cause_code)
);
