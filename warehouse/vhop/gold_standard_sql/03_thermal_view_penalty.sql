-- gold_standard_sql/03_thermal_view_penalty.sql
-- Metric: thermal_view_penalty (thang 0-100)
-- Công thức (tính độc lập từ dim_unit_master, ngưỡng đọc từ semantic_config):
--   hướng W/SW/NW: exposure >= west_exposure_high_pct  -> +40
--                  exposure >= west_exposure_low_pct   -> +20
--   view OBSTRUCTED hoặc obstruction <= obstruction_near_m -> +25
--   taboo view/floor (CEMETERY/WASTE_STATION/TEMPLE)     -> +30
--   cap 100
-- Trả về: (diagnostic_id, stored, recomputed)

SELECT d.diagnostic_id,
       d.thermal_view_penalty AS stored,
       LEAST(100,
           CASE
             WHEN u.balcony_orientation IN ('W','SW','NW') THEN
               CASE
                 WHEN u.west_facing_exposure_pct >=
                      (SELECT config_value::numeric FROM semantic_config
                       WHERE config_key='west_exposure_high_pct') THEN 40
                 WHEN u.west_facing_exposure_pct >=
                      (SELECT config_value::numeric FROM semantic_config
                       WHERE config_key='west_exposure_low_pct') THEN 20
                 ELSE 0
               END
             ELSE 0
           END
         + CASE
             WHEN u.view_primary_type = 'OBSTRUCTED'
               OR (u.view_obstruction_distance_m IS NOT NULL
                   AND u.view_obstruction_distance_m <=
                       (SELECT config_value::numeric FROM semantic_config
                        WHERE config_key='obstruction_near_m'))
             THEN 25 ELSE 0
           END
         + CASE
             WHEN u.taboo_view_type IN ('CEMETERY','WASTE_STATION','TEMPLE')
               OR u.is_taboo_floor
             THEN 30 ELSE 0
           END
       ) AS recomputed
FROM dm_unit_friction_diagnostics d
JOIN dim_unit_master u ON u.unit_key = d.unit_key;
