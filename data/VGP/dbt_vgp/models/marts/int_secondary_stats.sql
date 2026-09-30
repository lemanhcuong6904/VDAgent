{{ config(materialized='view') }}

-- Trung vi gia thu cap + co ban ghi trong 90 ngay gan nhat tinh tu ky ACTIVE
-- (khong hardcode ngay - lay tu int_active_snapshot, nguon duy nhat cho khai
-- niem "active"). Xap xi dung chung cho ca 6 ky (gan giong Python, vi
-- dim_secondary_market_comps khong bien doi theo tung ky snapshot).

-- c.project_id gio la hang so "PRJ-VGP" (khong con phan biet phan khu duoc) -
-- dung c.sub_project_id (alias ra project_id de dm_unit_friction_diagnostics.sql
-- join khong doi) giong nhu z.sub_project_id ben dm_unit_friction_diagnostics.sql.
select
    c.sub_project_id as project_id,
    c.unit_type,
    median(c.resale_price_per_m2_vnd) as secondary_median_ppm2,
    bool_or(date_diff('day', c.recorded_resale_date::date, a.active_snapshot_date::date) <= 90) as secondary_has_recent
from {{ ref('stg_dim_secondary_market_comps') }} c
cross join {{ ref('int_active_snapshot') }} a
group by 1, 2
