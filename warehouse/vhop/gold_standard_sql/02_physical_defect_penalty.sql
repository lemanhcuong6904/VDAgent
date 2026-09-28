-- gold_standard_sql/02_physical_defect_penalty.sql
-- Metric: physical_defect_penalty (thang 0-100)
-- Công thức (ngưỡng đọc từ semantic_config, không hard-code):
--   trash < defect_trash_near_m +30 / < defect_trash_far_m +15;
--   adjacent elevator +25; dark_bedroom*15 (cap 40);
--   efficiency < defect_efficiency_low +20 / < defect_efficiency_mid +10; cap 100
-- Trả về: (diagnostic_id, stored, recomputed)
SELECT d.diagnostic_id,
       d.physical_defect_penalty AS stored,
       LEAST(100,
           CASE WHEN u.distance_to_trash_room_m <
                     (SELECT config_value::numeric FROM semantic_config
                      WHERE config_key='defect_trash_near_m') THEN 30
                WHEN u.distance_to_trash_room_m <
                     (SELECT config_value::numeric FROM semantic_config
                      WHERE config_key='defect_trash_far_m') THEN 15
                ELSE 0 END
         + CASE WHEN u.is_adjacent_elevator THEN 25 ELSE 0 END
         + LEAST(40, u.dark_bedroom_count * 15)
         + CASE WHEN u.efficiency_ratio <
                     (SELECT config_value::numeric FROM semantic_config
                      WHERE config_key='defect_efficiency_low') THEN 20
                WHEN u.efficiency_ratio <
                     (SELECT config_value::numeric FROM semantic_config
                      WHERE config_key='defect_efficiency_mid') THEN 10
                ELSE 0 END
       ) AS recomputed
FROM dm_unit_friction_diagnostics d
JOIN dim_unit_master u ON u.unit_key = d.unit_key;
