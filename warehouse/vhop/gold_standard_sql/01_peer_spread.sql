-- gold_standard_sql/01_peer_spread.sql
-- Metric: price_spread_vs_peer_pct so với trung vị peer
-- Peer set theo engine `select_peers`: cùng dự án, cùng launch_batch, cùng
-- unit_type, cùng nhóm hướng (COOL = S/SE/E, còn lại HOT), |Δdiện tích| <=
-- net_area * peer_area_tolerance_pct/100, cùng dải tầng; nếu chưa đủ
-- min_peer_count thì mở rộng lần lượt sang dải tầng lân cận (HIGH, LOW, TOP, ...)
-- và dừng ngay khi đủ. Trung vị dùng quy ước số nguyên của engine:
-- lẻ -> phần tử giữa; chẵn -> floor((a+b)/2).
-- Trả về: (diagnostic_id, stored, recomputed)
WITH cfg AS (
    SELECT (SELECT config_value::numeric FROM semantic_config
            WHERE config_key='peer_area_tolerance_pct') / 100.0 AS tol,
           (SELECT config_value::int FROM semantic_config
            WHERE config_key='min_peer_count') AS min_peers
),
units AS (
    SELECT u.unit_key, u.project_key, u.unit_type, u.floor_band,
           u.net_area_m2, u.balcony_orientation,
           i.launch_batch_id, i.net_price_per_m2,
           CASE u.floor_band WHEN 'LOW' THEN 0 WHEN 'MID' THEN 1
                             WHEN 'HIGH' THEN 2 WHEN 'TOP' THEN 3 END AS band_idx,
           CASE WHEN u.balcony_orientation IN ('S','SE','E') THEN 'COOL'
                ELSE 'HOT' END AS orient_grp
    FROM dim_unit_master u
    JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key
),
matches AS (
    SELECT t.unit_key AS target_key, p.unit_key AS peer_key
    FROM units t
    JOIN units p
      ON p.unit_key <> t.unit_key
     AND p.project_key = t.project_key
     AND p.launch_batch_id = t.launch_batch_id
     AND p.unit_type = t.unit_type
     AND p.floor_band = t.floor_band
     AND p.orient_grp = t.orient_grp
     AND abs(p.net_area_m2 - t.net_area_m2) <= t.net_area_m2 * (SELECT tol FROM cfg)
),
exact_counts AS (
    SELECT t.unit_key AS target_key, count(m.peer_key) AS c
    FROM units t
    LEFT JOIN matches m ON m.target_key = t.unit_key
    GROUP BY t.unit_key
),
exp AS (
    SELECT t.unit_key AS target_key, p.unit_key AS peer_key, o.ord AS band_order
    FROM units t
    JOIN (VALUES (1, 1), (-1, 2), (2, 3), (-2, 4)) AS o(off, ord)
      ON t.band_idx + o.off BETWEEN 0 AND 3
    JOIN units p
      ON p.unit_key <> t.unit_key
     AND p.floor_band = (ARRAY['LOW','MID','HIGH','TOP'])[t.band_idx + o.off + 1]
     AND p.project_key = t.project_key
     AND p.launch_batch_id = t.launch_batch_id
     AND p.unit_type = t.unit_type
     AND p.orient_grp = t.orient_grp
     AND abs(p.net_area_m2 - t.net_area_m2) <= t.net_area_m2 * (SELECT tol FROM cfg)
),
exp_counts AS (
    SELECT target_key, band_order, count(*) AS c
    FROM exp GROUP BY target_key, band_order
),
cum AS (
    SELECT t.unit_key AS target_key, e.band_order,
           ec.c AS exact_c,
           sum(e.c) OVER (PARTITION BY t.unit_key ORDER BY e.band_order) AS exp_cum
    FROM units t
    JOIN exact_counts ec ON ec.target_key = t.unit_key
    LEFT JOIN exp_counts e ON e.target_key = t.unit_key
),
cutoff AS (
    SELECT target_key, min(band_order) AS cut
    FROM cum
    WHERE exact_c < (SELECT min_peers FROM cfg)
      AND exact_c + exp_cum >= (SELECT min_peers FROM cfg)
    GROUP BY target_key
),
selected_exp AS (
    SELECT e.target_key, e.peer_key
    FROM exp e
    JOIN exact_counts ec ON ec.target_key = e.target_key
    LEFT JOIN cutoff co ON co.target_key = e.target_key
    WHERE ec.c < (SELECT min_peers FROM cfg)
      AND (co.cut IS NULL OR e.band_order <= co.cut)
),
selected AS (
    SELECT target_key, peer_key FROM matches
    UNION
    SELECT target_key, peer_key FROM selected_exp
),
ordered AS (
    SELECT s.target_key, u.net_price_per_m2,
           row_number() OVER (PARTITION BY s.target_key
                              ORDER BY u.net_price_per_m2) AS rn,
           count(*) OVER (PARTITION BY s.target_key) AS n
    FROM selected s
    JOIN units u ON u.unit_key = s.peer_key
),
med AS (
    SELECT target_key,
           CASE WHEN max(n) % 2 = 1
                THEN max(net_price_per_m2) FILTER (WHERE rn = (n + 1) / 2)
                ELSE floor((max(net_price_per_m2) FILTER (WHERE rn = n / 2)
                          + max(net_price_per_m2) FILTER (WHERE rn = n / 2 + 1))
                           / 2.0)
           END AS peer_median
    FROM ordered
    GROUP BY target_key
)
SELECT d.diagnostic_id,
       d.price_spread_vs_peer_pct AS stored,
       CASE WHEN m.peer_median IS NULL THEN NULL
            ELSE round(((t.net_price_per_m2 - m.peer_median) / m.peer_median * 100)::numeric, 2)
       END AS recomputed
FROM dm_unit_friction_diagnostics d
JOIN units t ON t.unit_key = d.unit_key
LEFT JOIN med m ON m.target_key = d.unit_key;
