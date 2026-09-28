-- gold_standard_sql/07_cause_matrix.sql
-- Ma trận 8 nguyên nhân: tính lại ĐỘC LẬP bằng SQL từ nguồn tập nguyên nhân
-- khớp và severity_rank, rồi đối chiếu bảng bridge unit_diagnostic_causes.
-- Ngưỡng đọc từ semantic_config (không hard-code).
--
-- Thứ tự if của engine (causes.py::_matched) quyết định severity_rank; engine
-- giữ tối đa 3 hạng (matched[:3]). Mỗi nguyên nhân có `ord` cố định 1..8 trùng
-- thứ tự đó; row_number() theo ord tái lập rank rồi lọc rank<=3.
-- Các metric dẫn xuất (penalty/spread/gap/ticket/dropoff) đã được đối chiếu ở
-- 01-06; ở đây chỉ kiểm tra logic KÍCH HOẠT nguyên nhân trên các metric đó.
--
-- Trả về (FULL OUTER JOIN): (diagnostic_id, cause_code, recomputed_rank, stored_rank)
WITH cfg AS (
    SELECT
      (SELECT config_value::int     FROM semantic_config WHERE config_key='severe_defect_penalty_min')       AS severe_defect_penalty_min,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='thermal_penalty_min')             AS thermal_penalty_min,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='subsidy_support_min_mo')          AS subsidy_support_min_mo,
      (SELECT config_value::numeric FROM semantic_config WHERE config_key='secondary_gap_threshold_pct')     AS secondary_gap_threshold_pct,
      (SELECT config_value::numeric FROM semantic_config WHERE config_key='lump_sum_ticket_ratio_threshold') AS lump_sum_ticket_ratio_threshold,
      (SELECT config_value::numeric FROM semantic_config WHERE config_key='peer_spread_threshold_pct')       AS peer_spread_threshold_pct,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='defect_neutral_max')              AS defect_neutral_max,
      (SELECT config_value::numeric FROM semantic_config WHERE config_key='low_commission_threshold_pct')    AS low_commission_threshold_pct,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='low_view_threshold')              AS low_view_threshold,
      (SELECT config_value::numeric FROM semantic_config WHERE config_key='funnel_dropoff_threshold_pct')    AS funnel_dropoff_threshold_pct,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='min_booking_n')                   AS min_booking_n,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='high_view_threshold')             AS high_view_threshold,
      (SELECT config_value::int     FROM semantic_config WHERE config_key='high_visit_threshold')            AS high_visit_threshold
),
funnel AS (
    SELECT unit_key,
           sum(web_listing_views)    AS views,
           sum(site_visits_count)    AS visits,
           sum(booking_reservations) AS res
    FROM fact_sales_funnel_daily
    GROUP BY unit_key
),
base AS (
    SELECT d.diagnostic_id,
           d.physical_defect_penalty     AS pdp,
           d.thermal_view_penalty        AS tvp,
           d.price_spread_vs_peer_pct    AS spread,
           d.secondary_price_gap_pct     AS gap,
           d.ticket_size_vs_income_ratio AS ticket,
           d.funnel_dropoff_rate_pct     AS dropoff,
           p.is_sales_permit_issued,
           p.is_bank_guarantee_issued,
           i.subsidy_duration_mo,
           i.base_commission_pct,
           i.spiff_bonus_vnd,
           coalesce(f.views, 0)  AS views,
           coalesce(f.visits, 0) AS visits,
           coalesce(f.res, 0)    AS res
    FROM dm_unit_friction_diagnostics d
    JOIN dim_unit_master u              ON u.unit_key = d.unit_key
    JOIN dim_project_profile p          ON p.project_key = u.project_key
    JOIN fact_unit_inventory_snapshot i ON i.unit_key = d.unit_key
    LEFT JOIN funnel f                  ON f.unit_key = d.unit_key
),
matched AS (
    SELECT diagnostic_id, cause_code, ord FROM (
        SELECT b.diagnostic_id, 'LEGAL_PERMIT_BARRIER'::text AS cause_code, 1 AS ord
          FROM base b
         WHERE NOT b.is_sales_permit_issued OR NOT b.is_bank_guarantee_issued
        UNION ALL
        SELECT b.diagnostic_id, 'SEVERE_PHYSICAL_DEFECT', 2
          FROM base b, cfg
         WHERE b.pdp >= cfg.severe_defect_penalty_min
           AND b.spread IS NOT NULL AND b.spread >= 0
        UNION ALL
        SELECT b.diagnostic_id, 'EXTREME_THERMAL_EXPOSURE', 3
          FROM base b, cfg
         WHERE b.tvp >= cfg.thermal_penalty_min
           AND b.subsidy_duration_mo < cfg.subsidy_support_min_mo
        UNION ALL
        SELECT b.diagnostic_id, 'SECONDARY_ARBITRAGE', 4
          FROM base b, cfg
         WHERE b.gap IS NOT NULL AND b.gap >= cfg.secondary_gap_threshold_pct
        UNION ALL
        SELECT b.diagnostic_id, 'LUMP_SUM_TICKET_BARRIER', 5
          FROM base b, cfg
         WHERE b.ticket IS NOT NULL AND b.ticket >= cfg.lump_sum_ticket_ratio_threshold
           AND b.spread IS NOT NULL AND abs(b.spread) <= cfg.peer_spread_threshold_pct
        UNION ALL
        SELECT b.diagnostic_id, 'OVERPRICED_VS_PEER', 6
          FROM base b, cfg
         WHERE b.spread IS NOT NULL AND b.spread >= cfg.peer_spread_threshold_pct
           AND b.pdp <= cfg.defect_neutral_max
        UNION ALL
        SELECT b.diagnostic_id, 'LOW_SALES_INCENTIVE', 7
          FROM base b, cfg
         WHERE b.base_commission_pct <= cfg.low_commission_threshold_pct
           AND (b.spiff_bonus_vnd IS NULL OR b.spiff_bonus_vnd = 0)
           AND b.views < cfg.low_view_threshold
        UNION ALL
        SELECT b.diagnostic_id, 'DEEP_FUNNEL_DROP_OFF', 8
          FROM base b, cfg
         WHERE b.dropoff IS NOT NULL AND b.dropoff >= cfg.funnel_dropoff_threshold_pct
           AND b.res >= cfg.min_booking_n
           AND b.views >= cfg.high_view_threshold
           AND b.visits >= cfg.high_visit_threshold
    ) m
),
ranked AS (
    SELECT diagnostic_id, cause_code,
           row_number() OVER (PARTITION BY diagnostic_id ORDER BY ord) AS severity_rank
    FROM matched
),
recomputed AS (
    SELECT diagnostic_id, cause_code, severity_rank
    FROM ranked WHERE severity_rank <= 3
)
SELECT coalesce(r.diagnostic_id, c.diagnostic_id) AS diagnostic_id,
       coalesce(r.cause_code, c.cause_code)        AS cause_code,
       r.severity_rank                             AS recomputed_rank,
       c.severity_rank                             AS stored_rank
FROM recomputed r
FULL OUTER JOIN unit_diagnostic_causes c
  ON c.diagnostic_id = r.diagnostic_id AND c.cause_code = r.cause_code
ORDER BY 1, coalesce(r.severity_rank, c.severity_rank);
