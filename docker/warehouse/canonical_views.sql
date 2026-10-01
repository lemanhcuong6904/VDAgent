-- Canonical read layer over the DATA team's real warehouse (schema `gold`, DDL v3.1.0).
--
-- The Data, Insight and Compare agents read the real-estate DW through the Backend tools `re_*`, in the shape of
-- backend/vdagent_backend/re_warehouse/schema.sql (TEXT keys, decimals as text, `snapshot_date_key` in the manifest, ...).
-- This file exposes the real tables in exactly that shape as views of schema `re`, so no agent changes.
-- Columns the real warehouse does not hold are NULL (never invented); the two assumptions are marked ASSUMPTION.
-- The Backend connects as `vdagent_reader`, which can read schema `re` only and never `gold`.

CREATE SCHEMA IF NOT EXISTS re;

-- ASSUMPTION: the real manifest has no approval status; its single snapshot is the approved one (confirm with DATA).
-- ASSUMPTION: no load timestamp exists; the snapshot date at 00:00Z stands in for `loaded_at`.
CREATE OR REPLACE VIEW re.snapshot_manifest AS
SELECT snapshot_id,
       CAST(to_char(snapshot_date, 'YYYYMMDD') AS INTEGER) AS snapshot_date_key,
       'APPROVED'::text                                    AS status,
       semantic_version                                    AS semantic_config_version,
       to_char(snapshot_date, 'YYYY-MM-DD') || 'T00:00:00Z' AS loaded_at
FROM gold.snapshot_manifest;

CREATE OR REPLACE VIEW re.semantic_config AS
SELECT semantic_version AS config_version,
       config_key,
       -- JSON text, as the mock stores it: decimals and strings are JSON strings, integers and booleans are bare
       -- the real value is a percent (10), the agents' contract (D9) is a ratio ("0.10"): converted here, at the boundary
       CASE WHEN config_key = 'peer_area_tolerance_pct' THEN to_json(round(config_value::numeric / 100, 2)::text)::text
            WHEN value_type IN ('STRING', 'DECIMAL') THEN to_json(config_value)::text
            WHEN value_type = 'BOOLEAN' THEN lower(config_value)
            ELSE config_value END AS config_value,
       approval_status  AS status,
       description
FROM gold.semantic_config;

CREATE OR REPLACE VIEW re.dim_project_profile AS
SELECT project_key::text AS project_key,
       project_name,
       market_id,
       segment,
       CASE WHEN is_sales_permit_issued THEN 1 ELSE 0 END   AS is_sales_permit_issued,
       CASE WHEN is_bank_guarantee_issued THEN 1 ELSE 0 END AS is_bank_guarantee_issued
FROM gold.dim_project_profile;

CREATE OR REPLACE VIEW re.dim_zone_master AS
SELECT zone_key::text AS zone_key, zone_name, project_key::text AS project_key
FROM gold.dim_zone_master;

CREATE OR REPLACE VIEW re.dim_unit_master AS
SELECT u.unit_key::text            AS unit_key,
       u.unit_code,
       u.project_key::text         AS project_key,
       u.zone_key::text            AS zone_key,
       u.unit_type,
       u.gross_area_m2::text       AS area_m2,
       u.net_area_m2::text         AS net_area_m2,
       u.floor_number::int         AS floor_no,
       u.floor_band,
       u.balcony_orientation,
       u.view_primary_type,
       i.launch_batch_id,          -- the real dimension has no launch batch or release date: taken from the snapshot row
       i.release_date::text        AS release_date
FROM gold.dim_unit_master u
LEFT JOIN gold.fact_unit_inventory_snapshot i
       ON i.unit_key = u.unit_key AND i.snapshot_date_key = (SELECT MAX(snapshot_date_key) FROM re.snapshot_manifest);

-- Internal: which project and zone each unit belongs to; the Backend scopes the unit-keyed tables through it.
-- (Not one of the tables agents may query.)
CREATE OR REPLACE VIEW re.unit_scope AS
SELECT unit_key::text AS unit_key, project_key::text AS project_key, zone_key::text AS zone_key
FROM gold.dim_unit_master;

-- ASSUMPTION: the real warehouse keeps the commission on each inventory row, the agents read it per channel. A channel's
-- base commission is taken as the lowest rate on its rows (the others are uplifts); the spiff bonus stays unknown.
CREATE OR REPLACE VIEW re.dim_sales_channel AS
SELECT c.channel_key::text AS channel_key,
       c.channel_name,
       (SELECT MIN(f.base_commission_pct) FROM gold.fact_unit_inventory_snapshot f WHERE f.channel_key = c.channel_key)::text
                          AS base_commission_pct,
       NULL::bigint       AS spiff_bonus_vnd
FROM gold.dim_sales_channel c;

CREATE OR REPLACE VIEW re.fact_unit_inventory_snapshot AS
SELECT f.unit_key::text       AS unit_key,
       f.snapshot_date_key,
       f.project_key::text    AS project_key,
       f.zone_key::text       AS zone_key,
       f.channel_key::text    AS channel_key,
       f.inventory_status,
       f.unsold_days_dom,
       f.release_date::text   AS release_date,
       d.full_date::text      AS snapshot_date,
       f.sold_date::text      AS sold_date,
       f.asking_price_vnd,
       f.net_price_per_m2
FROM gold.fact_unit_inventory_snapshot f
JOIN gold.dim_date d ON d.date_key = f.snapshot_date_key;

CREATE OR REPLACE VIEW re.fact_sales_channel_performance AS
SELECT channel_key::text AS channel_key,
       project_key::text AS project_key,
       snapshot_date_key,
       NULL::int         AS web_listing_views,
       locked_inventory_over_90d,
       absorption_rate_pct::text AS absorption_rate_pct
FROM gold.fact_sales_channel_performance;

CREATE OR REPLACE VIEW re.fact_unit_price_history AS
SELECT h.unit_key::text          AS unit_key,
       d.full_date::text         AS effective_date,
       h.new_asking_price_vnd    AS asking_price_vnd,
       NULL::bigint              AS net_price_per_m2
FROM gold.fact_unit_price_history h
JOIN gold.dim_date d ON d.date_key = h.effective_date_key;

CREATE OR REPLACE VIEW re.fact_sales_funnel_daily AS
SELECT unit_key::text                 AS unit_key,
       date_key,
       inquiry_leads_count::int       AS leads,
       site_visits_count::int         AS site_visits,
       booking_reservations::int      AS bookings,
       booking_cancellations::int     AS cancellations,
       NULL::int                      AS contracts,
       cancellation_reason
FROM gold.fact_sales_funnel_daily;

CREATE OR REPLACE VIEW re.dim_secondary_market_comps AS
SELECT c.comp_id                       AS comp_key,
       p.project_key::text             AS project_key,
       c.unit_type,
       c.recorded_resale_date::text    AS transaction_date,
       c.resale_price_per_m2_vnd       AS price_per_m2
FROM gold.dim_secondary_market_comps c
JOIN gold.dim_project_profile p ON p.project_id = c.project_id;

CREATE OR REPLACE VIEW re.fact_market_macro_monthly AS
SELECT market_id,
       segment,
       date_key / 100                           AS month_key,
       floating_mortgage_rate_pct::text         AS mortgage_rate_pct,
       absorption_rate_pct::text                AS absorption_rate_pct,
       months_of_inventory_moi::text            AS months_of_inventory,
       macro_price_to_income_ratio::text        AS price_to_income_ratio
FROM gold.fact_market_macro_monthly;

-- The real warehouse keeps infrastructure global and points each project at its primary asset.
CREATE OR REPLACE VIEW re.dim_infrastructure_assets AS
SELECT p.project_id || ':' || i.infra_id                     AS asset_key,
       p.project_key::text                                   AS project_key,
       i.infra_type                                          AS asset_type,
       i.infra_name                                          AS asset_name,
       round(p.distance_to_primary_infra_m / 1000.0, 2)::text AS distance_km,
       i.lifecycle_stage                                     AS status
FROM gold.dim_project_profile p
JOIN gold.dim_infrastructure_assets i ON i.infra_id = p.primary_infra_id;

CREATE OR REPLACE VIEW re.dm_unit_friction_diagnostics AS
SELECT g.unit_key::text                       AS unit_key,
       g.snapshot_date_key,
       g.primary_cause_code,
       g.price_spread_vs_peer_pct::text       AS price_spread_vs_peer_pct,
       NULL::int                              AS is_peer_sample_constrained,  -- not in the real mart
       NULL::int                              AS peer_n,                      -- not in the real mart
       g.physical_defect_penalty::int         AS physical_defect_penalty,
       g.thermal_view_penalty::int            AS thermal_view_penalty,
       i.subsidy_duration_mo::int             AS subsidy_duration_mo,         -- lives on the inventory row
       g.secondary_price_gap_pct::text        AS secondary_price_gap_pct,
       g.ticket_size_vs_income_ratio::text    AS ticket_size_vs_income_ratio,
       g.funnel_dropoff_rate_pct::text        AS funnel_dropoff_rate_pct,
       u.west_facing_exposure_pct::text       AS west_facing_exposure_pct,    -- lives on the unit dimension
       g.recommended_action
FROM gold.dm_unit_friction_diagnostics g
LEFT JOIN gold.dim_unit_master u ON u.unit_key = g.unit_key
LEFT JOIN gold.fact_unit_inventory_snapshot i
       ON i.unit_key = g.unit_key AND i.snapshot_date_key = g.snapshot_date_key;

CREATE OR REPLACE VIEW re.unit_diagnostic_causes AS
SELECT unit_key::text AS unit_key, snapshot_date_key, cause_code, severity_rank::int AS severity_rank,
       attribution_score::text AS attribution_score
FROM gold.unit_diagnostic_causes;

-- Read-only reader (docker/warehouse/apply-views.sh creates the role with its password from the environment; nothing
-- secret lives in this file): schema `re` only, read-only transactions, temp views first on the search path.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'vdagent_reader') THEN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO vdagent_reader', current_database());
    GRANT USAGE ON SCHEMA re TO vdagent_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA re TO vdagent_reader;
    REVOKE ALL ON SCHEMA gold FROM vdagent_reader;
    ALTER ROLE vdagent_reader SET default_transaction_read_only = on;
    ALTER ROLE vdagent_reader SET search_path = pg_temp, re;
  END IF;
END $$;
