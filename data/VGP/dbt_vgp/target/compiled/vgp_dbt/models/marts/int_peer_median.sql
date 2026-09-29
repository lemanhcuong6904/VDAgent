

-- Peer Group 2 tang (giong logic vector hoa trong generate_vgp_mock.py):
-- tang 1 = cung PHAN KHU + loai can + nhom tang (can toi thieu 5 mau)
-- tang 2 (fallback) = cung PHAN KHU + loai can
-- Dung z.sub_project_id (KHONG phai f.project_key - gio la hang so 300 duy
-- nhat theo warehouse/id_registry.json, khong con phan biet phan khu duoc).

with base as (
    select
        f.snapshot_date_key,
        f.unit_key,
        z.sub_project_id,
        f.asking_price_per_m2,
        u.unit_type,
        u.floor_band
    from "vgp"."main_staging"."stg_fact_unit_inventory_snapshot" f
    join "vgp"."main_staging"."stg_dim_unit_master" u on f.unit_key = u.unit_key
    join "vgp"."main_staging"."stg_dim_zone_master" z on u.zone_key = z.zone_key
),

tier1 as (
    select
        snapshot_date_key, sub_project_id, unit_type, floor_band,
        median(asking_price_per_m2) as med1,
        count(*) as cnt1
    from base
    group by 1, 2, 3, 4
),

tier2 as (
    select
        snapshot_date_key, sub_project_id, unit_type,
        median(asking_price_per_m2) as med2
    from base
    group by 1, 2, 3
)

select
    b.snapshot_date_key,
    b.unit_key,
    b.asking_price_per_m2,
    case when t1.cnt1 >= 5 then t1.med1 else t2.med2 end as peer_median_ppm2,
    round(
        100.0 * (b.asking_price_per_m2 - (case when t1.cnt1 >= 5 then t1.med1 else t2.med2 end))
        / (case when t1.cnt1 >= 5 then t1.med1 else t2.med2 end), 2
    ) as price_spread_vs_peer_pct
from base b
left join tier1 t1 on b.snapshot_date_key = t1.snapshot_date_key and b.sub_project_id = t1.sub_project_id
    and b.unit_type = t1.unit_type and b.floor_band = t1.floor_band
left join tier2 t2 on b.snapshot_date_key = t2.snapshot_date_key and b.sub_project_id = t2.sub_project_id
    and b.unit_type = t2.unit_type