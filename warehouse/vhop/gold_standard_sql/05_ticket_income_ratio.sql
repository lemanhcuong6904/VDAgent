-- gold_standard_sql/05_ticket_income_ratio.sql
-- Metric: ticket_size_vs_income_ratio = net_price_vnd / median_household_income_vnd
-- Thu nhập lấy theo segment của dự án từ fact_market_macro_monthly (một giá trị
-- cho mỗi segment). Kết quả làm tròn 1 chữ số thập phân (HALF_UP) như engine.
-- Trả về: (diagnostic_id, stored, recomputed)

SELECT d.diagnostic_id,
       d.ticket_size_vs_income_ratio AS stored,
       CASE
         WHEN inc.income_vnd IS NULL OR inc.income_vnd = 0 THEN NULL
         ELSE round(i.net_price_vnd::numeric / inc.income_vnd, 1)
       END AS recomputed
FROM dm_unit_friction_diagnostics d
JOIN fact_unit_inventory_snapshot i ON i.unit_key = d.unit_key
JOIN dim_unit_master u ON u.unit_key = d.unit_key
JOIN dim_project_profile p ON p.project_key = u.project_key
LEFT JOIN LATERAL (
    SELECT max(m.median_household_income_vnd) AS income_vnd
    FROM fact_market_macro_monthly m
    WHERE m.segment = p.segment
) inc ON TRUE;
