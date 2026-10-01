{{ config(materialized='table') }}

-- Mart CONSOLIDATION moi (mo rong ngoai schema v3 goc): tong hop hieu suat
-- tung san phan phoi tu 2 bang mo rong Bridge + Attribution. KHONG dung lai
-- hay nhan ban logic ma tran 8 nguyen nhan cua dm_unit_friction_diagnostics -
-- day la goc nhin hoan toan khac (hieu suat kenh/marketing attribution), dung
-- rieng stg_bridge_unit_channel_history + stg_fact_funnel_attribution.
--
-- Grain: 1 dong / 1 san phan phoi (channel_key) - tong hop toan bo lich su
-- (khong theo tung ky snapshot, vi Bridge/Attribution la du lieu xuyen suot
-- vong doi can, khong phai snapshot dinh ky).
--
-- Khoa noi: channel_key (dim_sales_channel) <- bridge_unit_channel_history.channel_key
--                                            <- fact_funnel_attribution.channel_key

with bridge_agg as (
    select
        channel_key,
        count(distinct unit_key) as units_ever_assigned,
        count(distinct case when is_current then unit_key end) as units_currently_assigned,
        count(case when assignment_type = 'EXCLUSIVE' then 1 end) as exclusive_assignments_count,
        count(case when assignment_type = 'CO_LISTING' then 1 end) as co_listing_assignments_count
    from {{ ref('stg_bridge_unit_channel_history') }}
    group by channel_key
),

attribution_agg as (
    select
        channel_key,
        count(*) as attributed_touchpoints_count,
        count(distinct unit_key) as attributed_converted_units_count,
        round(sum(attribution_weight), 2) as total_attribution_weight,
        round(avg(attribution_weight), 4) as avg_attribution_weight_per_touchpoint
    from {{ ref('stg_fact_funnel_attribution') }}
    group by channel_key
)

select
    c.channel_key,
    c.channel_name,
    c.channel_tier,
    coalesce(b.units_ever_assigned, 0) as units_ever_assigned,
    coalesce(b.units_currently_assigned, 0) as units_currently_assigned,
    coalesce(b.exclusive_assignments_count, 0) as exclusive_assignments_count,
    coalesce(b.co_listing_assignments_count, 0) as co_listing_assignments_count,
    coalesce(a.attributed_touchpoints_count, 0) as attributed_touchpoints_count,
    coalesce(a.attributed_converted_units_count, 0) as attributed_converted_units_count,
    coalesce(a.total_attribution_weight, 0) as total_attribution_weight,
    a.avg_attribution_weight_per_touchpoint,
    round(100.0 * coalesce(a.attributed_converted_units_count, 0)
          / nullif(coalesce(b.units_ever_assigned, 0), 0), 2) as conversion_rate_pct
from {{ ref('stg_dim_sales_channel') }} c
left join bridge_agg b on c.channel_key = b.channel_key
left join attribution_agg a on c.channel_key = a.channel_key
