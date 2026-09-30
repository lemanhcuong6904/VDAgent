
  
  create view "vgp"."main_staging"."stg_dim_zone_master__dbt_tmp" as (
    select
    zone_key,
    zone_id,
    project_key,
    zone_name,
    zone_type,
    total_floors,
    basement_floors,
    units_per_floor,
    passenger_elevators,
    elevator_ratio,
    handover_standard,
    -- Moi (mo rong): thuoc tinh phan khu chuyen xuong tu dim_project_profile
    -- (project_key gio la 1 hang duy nhat theo warehouse/id_registry.json)
    sub_project_id,
    sub_project_name,
    segment,
    construction_status,
    construction_progress_pct,
    is_sales_permit_issued,
    is_bank_guarantee_issued,
    expected_handover_date
from '../data/05_dim_zone_master.csv'
  );
