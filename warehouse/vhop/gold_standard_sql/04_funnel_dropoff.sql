-- gold_standard_sql/04_funnel_dropoff.sql
-- Metric: funnel_dropoff_rate_pct = cancellations / reservations * 100
-- Trả về: (diagnostic_id, stored, recomputed)
SELECT d.diagnostic_id,
       d.funnel_dropoff_rate_pct AS stored,
       CASE WHEN sum(f.booking_reservations) = 0 THEN NULL
            ELSE round(100.0 * sum(f.booking_cancellations)
                       / sum(f.booking_reservations), 2) END AS recomputed
FROM dm_unit_friction_diagnostics d
LEFT JOIN fact_sales_funnel_daily f ON f.unit_key = d.unit_key
GROUP BY d.diagnostic_id, d.funnel_dropoff_rate_pct;
