-- gold_standard_sql/06_secondary_price_gap.sql
-- Metric: secondary_price_gap_pct
--   = (net_price_per_m2 - comp_median) / comp_median * 100
-- Comp cùng (unit_type, floor_band, balcony_orientation), còn trong cửa sổ độ mới
-- `secondary_comp_recency_days` tính từ snapshot_manifest.snapshot_date.
-- Trung vị theo quy ước số nguyên của engine: lẻ -> phần tử giữa;
-- chẵn -> floor((a+b)/2). Kết quả làm tròn 2 chữ số thập phân (HALF_UP).
-- Trả về: (diagnostic_id, stored, recomputed)

WITH cfg AS (
    SELECT (SELECT config_value::int FROM semantic_config
            WHERE config_key='secondary_comp_recency_days') AS recency
),
snap AS (
    SELECT snapshot_date FROM snapshot_manifest LIMIT 1
),
comps AS (
    SELECT c.unit_type, c.floor_band, c.balcony_orientation,
           c.resale_price_per_m2_vnd
    FROM dim_secondary_market_comps c
    CROSS JOIN snap s
    WHERE (s.snapshot_date - c.recorded_resale_date) <= (SELECT recency FROM cfg)
),
ranked AS (
    SELECT unit_type, floor_band, balcony_orientation,
           resale_price_per_m2_vnd,
           row_number() OVER (
               PARTITION BY unit_type, floor_band, balcony_orientation
               ORDER BY resale_price_per_m2_vnd) AS rn,
           count(*) OVER (
               PARTITION BY unit_type, floor_band, balcony_orientation) AS n
    FROM comps
),
med AS (
    SELECT unit_type, floor_band, balcony_orientation,
           CASE WHEN max(n) % 2 = 1
                THEN max(resale_price_per_m2_vnd) FILTER (WHERE rn = (n + 1) / 2)
                ELSE floor(
                    (max(resale_price_per_m2_vnd) FILTER (WHERE rn = n / 2)
                   + max(resale_price_per_m2_vnd) FILTER (WHERE rn = n / 2 + 1))
                    / 2.0)
           END AS comp_median
    FROM ranked
    GROUP BY unit_type, floor_band, balcony_orientation
)
SELECT d.diagnostic_id,
       d.secondary_price_gap_pct AS stored,
       CASE
         WHEN m.comp_median IS NULL OR m.comp_median = 0 THEN NULL
         ELSE round((i.net_price_per_m2 - m.comp_median) / m.comp_median * 100, 2)
       END AS recomputed
FROM dm_unit_friction_diagnostics d
JOIN fact_unit_inventory_snapshot i ON i.unit_key = d.unit_key
JOIN dim_unit_master u ON u.unit_key = d.unit_key
LEFT JOIN med m
       ON m.unit_type = u.unit_type
      AND m.floor_band = u.floor_band
      AND m.balcony_orientation = u.balcony_orientation;
