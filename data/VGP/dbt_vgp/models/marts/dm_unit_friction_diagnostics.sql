{{ config(materialized='table') }}

-- Ban SQL/dbt cua ma tran 8 nguyen nhan cot loi (muc 4.3 tai lieu goc), tinh
-- lai bang SQL thay vi Python (generate_vgp_mock.py) - de doi chieu 2 ket qua
-- phai khop nhau (xem test dm_diagnostics_matches_python trong schema.yml).
-- Nguong dung nguyen: OVERDUE_THRESHOLD_DAYS=90, SECONDARY_GAP=15,
-- PIR_TRIGGER=20, PEER_OVERPRICE=8, LOW_COMMISSION=1.5, FUNNEL_DROPOFF=60.

with latest_income as (
    select median_household_income_vnd as income
    from {{ ref('stg_fact_market_macro_monthly') }}
    order by date_key desc limit 1
),

candidates as (
    select
        f.snapshot_date_key,
        f.unit_key,
        f.project_key,
        f.zone_key,
        f.unsold_days_dom,
        f.asking_price_vnd,
        f.asking_price_per_m2,
        f.subsidy_duration_mo,
        f.base_commission_pct,
        f.spiff_bonus_vnd,
        u.unit_code,
        u.unit_type,
        -- project_key gio la 1 hang duy nhat (300) theo warehouse/id_registry.json
        -- nen KHONG con phan biet duoc phan khu - is_sales_permit_issued/
        -- is_bank_guarantee_issued/project_id/project_name doc tu dim_zone_master
        -- (z.*, da JOIN san qua zone_key) thay vi dim_project_profile.
        z.sub_project_id as project_id,
        z.sub_project_name as project_name,
        z.is_sales_permit_issued,
        z.is_bank_guarantee_issued,
        z.zone_name
    from {{ ref('stg_fact_unit_inventory_snapshot') }} f
    join {{ ref('stg_dim_unit_master') }} u on f.unit_key = u.unit_key
    join {{ ref('stg_dim_zone_master') }} z on f.zone_key = z.zone_key
    where f.inventory_status = 'AVAILABLE' and f.unsold_days_dom > 90
),

enriched as (
    select
        c.*,
        round(c.asking_price_vnd / li.income, 1) as ticket_size_vs_income_ratio,
        dt.physical_defect_penalty,
        dt.thermal_view_penalty,
        pm.price_spread_vs_peer_pct,
        ss.secondary_median_ppm2,
        coalesce(ss.secondary_has_recent, false) as secondary_has_recent,
        round(100.0 * (c.asking_price_per_m2 - ss.secondary_median_ppm2) / ss.secondary_median_ppm2, 2) as secondary_price_gap_pct,
        fd.funnel_dropoff_rate_pct
    from candidates c
    cross join latest_income li
    left join {{ ref('int_defect_thermal_penalty') }} dt on c.unit_key = dt.unit_key
    left join {{ ref('int_peer_median') }} pm on c.snapshot_date_key = pm.snapshot_date_key and c.unit_key = pm.unit_key
    left join {{ ref('int_secondary_stats') }} ss on c.project_id = ss.project_id
        and c.unit_type = ss.unit_type
    left join {{ ref('int_funnel_dropoff') }} fd on c.unit_key = fd.unit_key
)

select
    'DIAG-' || strftime(strptime(cast(snapshot_date_key as varchar), '%Y%m%d'), '%Y%m%d') || '-' || unit_code as diagnostic_id,
    snapshot_date_key,
    unit_key,
    unit_code,
    project_name,
    zone_name,
    unsold_days_dom,
    price_spread_vs_peer_pct,
    ticket_size_vs_income_ratio,
    physical_defect_penalty,
    thermal_view_penalty,
    secondary_price_gap_pct,
    funnel_dropoff_rate_pct,
    case
        when not is_sales_permit_issued or not is_bank_guarantee_issued
            then 'LEGAL_PERMIT_BARRIER'
        when physical_defect_penalty >= 25 and coalesce(price_spread_vs_peer_pct, 0) >= 0
            then 'SEVERE_PHYSICAL_DEFECT'
        when thermal_view_penalty >= 40 and subsidy_duration_mo < 24
            then 'EXTREME_THERMAL_EXPOSURE'
        when secondary_price_gap_pct >= 15 and secondary_has_recent
            then 'SECONDARY_ARBITRAGE'
        when ticket_size_vs_income_ratio >= 20 and abs(coalesce(price_spread_vs_peer_pct, 999)) < 10
            then 'LUMP_SUM_TICKET_BARRIER'
        when price_spread_vs_peer_pct >= 8 and physical_defect_penalty < 25 and thermal_view_penalty < 25
            then 'OVERPRICED_VS_PEER'
        when base_commission_pct <= 1.5 and spiff_bonus_vnd is null
            then 'LOW_SALES_INCENTIVE'
        when funnel_dropoff_rate_pct >= 60
            then 'DEEP_FUNNEL_DROP_OFF'
        else 'MULTI_FACTOR_UNCLASSIFIED'
    end as primary_cause_code,
    case
        when not is_sales_permit_issued or not is_bank_guarantee_issued
            then 'EXPEDITE_LEGAL_PROCEDURES: Tam dung ban hang dai tra; hoan thien thu tuc So Xay dung va thu cam ket bao lanh ban giao.'
        when physical_defect_penalty >= 25 and coalesce(price_spread_vs_peer_pct, 0) >= 0
            then 'DEFECT_COMPENSATION_DISCOUNT: Thiet lap chinh sach giam gia chao truc tiep 5%-8% de bu tru loi cong nang.'
        when thermal_view_penalty >= 40 and subsidy_duration_mo < 24
            then 'INSULATION_INTERIOR_PACKAGE: Tang goi thi cong noi that cach nhiet, dan kinh Low-E va mien 3 nam phi quan ly.'
        when secondary_price_gap_pct >= 15 and secondary_has_recent
            then 'EXTENDED_PAYMENT_SCHEDULE: Gian tien do thanh toan, tang voucher de keo gia rong ve can bang.'
        when ticket_size_vs_income_ratio >= 20 and abs(coalesce(price_spread_vs_peer_pct, 999)) < 10
            then 'BANK_SUBSIDY_EXTENSION: Tang thoi han ho tro lai suat 0% tu 18 len 36 thang va keo dai an han no goc.'
        when price_spread_vs_peer_pct >= 8 and physical_defect_penalty < 25 and thermal_view_penalty < 25
            then 'TARGETED_PRICE_CORRECTION: Dieu chinh don gia niem yet ve muc trung vi cua nhom tuong dong.'
        when base_commission_pct <= 1.5 and spiff_bonus_vnd is null
            then 'BOOST_BROKER_COMMISSION: Nang ty le hoa hong len 3.0% va kich hoat thuong nong 50-100 trieu VND.'
        when funnel_dropoff_rate_pct >= 60
            then 'SALES_PITCH_AUDIT: Thanh tra quy trinh tu van cua san moi gioi, ra soat cam ket tien do va phuong thuc giai ngan.'
        else 'MANUAL_REVIEW: Khong khop du kien kich hoat ro rang trong ma tran 8 nguyen nhan; can chuyen gia ra soat thu cong.'
    end as recommended_action
from enriched
