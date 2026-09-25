-- Run with psql -v ON_ERROR_STOP=1 after data/load_vhsc_mock.sql.
BEGIN;
CREATE TEMP TABLE expected_counts (table_name text PRIMARY KEY, expected integer) ON COMMIT DROP;
INSERT INTO expected_counts VALUES
('snapshot_manifest',1), ('semantic_config',12), ('dim_date',181),
('dim_infrastructure_assets',4), ('dim_project_profile',2), ('dim_zone_master',7),
('dim_unit_master',1216), ('dim_sales_channel',8), ('dim_secondary_market_comps',96),
('fact_market_macro_monthly',24), ('fact_unit_price_history',480),
('fact_sales_funnel_daily',4864), ('fact_unit_inventory_snapshot',1216),
('fact_sales_channel_performance',16), ('dm_unit_friction_diagnostics',136),
('unit_diagnostic_causes',193);

DO $qa$
DECLARE
    item record;
    actual integer;
BEGIN
    FOR item IN SELECT * FROM expected_counts LOOP
        EXECUTE format('SELECT count(*) FROM dw.%I', item.table_name) INTO actual;
        IF actual <> item.expected THEN
            RAISE EXCEPTION 'Count mismatch %. Expected %, got %', item.table_name, item.expected, actual;
        END IF;
    END LOOP;
    IF (SELECT count(*) FROM expected_counts) <> 16 THEN RAISE EXCEPTION 'Missing table target'; END IF;

    IF (SELECT count(*) FROM dw.dim_unit_master u JOIN dw.dim_project_profile p USING (project_key)
        WHERE p.project_id = 'PRJ-VHSC-HN') <> 1200 THEN RAISE EXCEPTION 'Target project unit count'; END IF;
    IF (SELECT count(*) FROM dw.dim_unit_master u JOIN dw.dim_project_profile p USING (project_key)
        WHERE p.project_id = 'PRJ-VHSC-LEGAL-MOCK') <> 16 THEN RAISE EXCEPTION 'Legal fixture unit count'; END IF;
    IF EXISTS (SELECT 1 FROM dw.dim_unit_master WHERE ext_attributes->>'data_origin' <> 'synthetic')
        THEN RAISE EXCEPTION 'Unlabeled synthetic unit'; END IF;
    IF EXISTS (SELECT 1 FROM dw.dim_secondary_market_comps WHERE comp_id NOT LIKE 'MOCK-COMP-%')
        THEN RAISE EXCEPTION 'Unlabeled mock comparator'; END IF;

    IF (SELECT count(*) FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.project_key = 1 AND i.inventory_status = 'SOLD') <> 816 THEN RAISE EXCEPTION 'Sold allocation'; END IF;
    IF (SELECT count(*) FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.project_key = 1 AND i.inventory_status = 'BOOKED') <> 84 THEN RAISE EXCEPTION 'Booked allocation'; END IF;
    IF (SELECT count(*) FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.project_key = 1 AND i.inventory_status = 'AVAILABLE') <> 300 THEN RAISE EXCEPTION 'Available allocation'; END IF;
    IF (SELECT count(*) FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.project_key = 1 AND i.is_overdue_flag) <> 120 THEN RAISE EXCEPTION 'Target overdue count'; END IF;

    IF EXISTS (
        SELECT 1 FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE i.project_key <> u.project_key OR i.zone_key <> u.zone_key
           OR i.asking_price_per_m2 <> ROUND(i.asking_price_vnd::numeric / u.net_area_m2)
           OR i.net_price_per_m2 <> ROUND(i.net_price_vnd::numeric / u.net_area_m2)
           OR i.is_overdue_flag <> (i.inventory_status = 'AVAILABLE' AND i.unsold_days_dom > 90)
    ) THEN RAISE EXCEPTION 'Inventory/unit calculation mismatch'; END IF;

    IF EXISTS (
        SELECT 1 FROM dw.fact_unit_price_history h JOIN dw.fact_unit_inventory_snapshot i USING (unit_key)
        WHERE h.new_asking_price_vnd <> i.asking_price_vnd
    ) THEN RAISE EXCEPTION 'Price history does not match snapshot'; END IF;

    IF EXISTS (
        SELECT 1 FROM dw.fact_sales_channel_performance p
        LEFT JOIN LATERAL (
            SELECT count(*) AS assigned, count(*) FILTER (WHERE inventory_status = 'SOLD') AS sold
            FROM dw.fact_unit_inventory_snapshot i
            WHERE i.channel_key = p.channel_key AND i.project_key = p.project_key
              AND i.snapshot_date_key = p.snapshot_date_key
        ) s ON TRUE
        WHERE p.assigned_units_count <> s.assigned OR p.sold_units_count <> s.sold
    ) THEN RAISE EXCEPTION 'Channel performance aggregate mismatch'; END IF;

    IF (SELECT count(DISTINCT primary_cause_code) FROM dw.dm_unit_friction_diagnostics) <> 8
        THEN RAISE EXCEPTION 'Missing primary cause'; END IF;
    IF EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics GROUP BY primary_cause_code HAVING count(*) < 10
    ) THEN RAISE EXCEPTION 'Insufficient cause coverage'; END IF;
    IF EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics d
        JOIN dw.fact_unit_inventory_snapshot i USING (unit_key, snapshot_date_key)
        WHERE i.inventory_status <> 'AVAILABLE' OR i.unsold_days_dom <= 90
           OR d.unsold_days_dom <> i.unsold_days_dom
    ) THEN RAISE EXCEPTION 'Invalid diagnostic population'; END IF;
    IF EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics d JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.unit_id IN ('VHSC-U-00001', 'VHSC-U-00007', 'VHSC-U-00182')
    ) THEN RAISE EXCEPTION 'Negative control was diagnosed'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics d JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.unit_id = 'VHSC-U-00247' AND d.unsold_days_dom = 91
    ) THEN RAISE EXCEPTION 'DOM 91 boundary case was missed'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM dw.fact_unit_inventory_snapshot i JOIN dw.dim_unit_master u USING (unit_key)
        WHERE u.unit_id = 'VHSC-U-00182' AND i.inventory_status = 'AVAILABLE' AND i.unsold_days_dom = 90
    ) THEN RAISE EXCEPTION 'DOM 90 boundary fixture missing'; END IF;
    IF EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics d
        LEFT JOIN dw.unit_diagnostic_causes c USING (diagnostic_id)
        GROUP BY d.diagnostic_id, d.primary_cause_code
        HAVING coalesce(sum(c.attribution_score),0) <> 1.000
           OR count(*) FILTER (WHERE c.severity_rank = 1 AND c.cause_code = d.primary_cause_code) <> 1
    ) THEN RAISE EXCEPTION 'Bridge attribution or primary rank mismatch'; END IF;

    IF EXISTS (
        SELECT 1 FROM dw.dm_unit_friction_diagnostics d
        JOIN dw.fact_unit_inventory_snapshot i USING (unit_key, snapshot_date_key)
        JOIN dw.dim_unit_master u USING (unit_key)
        JOIN dw.dim_project_profile p ON p.project_key = u.project_key
        LEFT JOIN LATERAL (
            SELECT sum(web_listing_views) AS views, sum(site_visits_count) AS visits,
                   sum(booking_reservations) AS bookings, sum(booking_cancellations) AS cancellations
            FROM dw.fact_sales_funnel_daily f WHERE f.unit_key = d.unit_key
        ) f ON TRUE
        WHERE (d.primary_cause_code = 'LEGAL_PERMIT_BARRIER' AND
               (p.project_id <> 'PRJ-VHSC-LEGAL-MOCK' OR (p.is_sales_permit_issued AND p.is_bank_guarantee_issued)))
           OR (d.primary_cause_code = 'SEVERE_PHYSICAL_DEFECT' AND
               (d.physical_defect_penalty < 25 OR i.discount_pct <> 0))
           OR (d.primary_cause_code = 'EXTREME_THERMAL_EXPOSURE' AND
               (d.thermal_view_penalty < 40 OR i.subsidy_duration_mo >= 24))
           OR (d.primary_cause_code = 'SECONDARY_ARBITRAGE' AND
               (d.secondary_price_gap_pct <= 15 OR d.secondary_price_gap_pct IS NULL))
           OR (d.primary_cause_code = 'LUMP_SUM_TICKET_BARRIER' AND
               (d.ticket_size_vs_income_ratio <= 25 OR d.price_spread_vs_peer_pct > 0))
           OR (d.primary_cause_code = 'OVERPRICED_VS_PEER' AND
               (d.price_spread_vs_peer_pct <= 8 OR d.physical_defect_penalty > 0 OR d.thermal_view_penalty > 0))
           OR (d.primary_cause_code = 'LOW_SALES_INCENTIVE' AND
               (i.base_commission_pct > 1.5 OR coalesce(i.spiff_bonus_vnd,0) > 0 OR f.views >= 30))
           OR (d.primary_cause_code = 'DEEP_FUNNEL_DROP_OFF' AND
               (d.funnel_dropoff_rate_pct < 60 OR f.views <= 250 OR f.visits <= 25
                OR f.bookings < 10 OR f.cancellations < 8))
    ) THEN RAISE EXCEPTION 'Scenario evidence mismatch'; END IF;

    RAISE NOTICE 'PASS: all 16 counts, 1200 target units, status allocation, 8 causes, formulas, lineage and scenario evidence';
END
$qa$;
ROLLBACK;
