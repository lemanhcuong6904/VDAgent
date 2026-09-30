
  
  create view "vgp"."main_staging"."stg_dim_unit_master__dbt_tmp" as (
    select
    unit_key,
    -- unit_id (rieng, prefix "VGP-U-" tu unit_key) da BI BO - khong phai field
    -- trong warehouse/id_registry.json, unit_code gio da chuan hoa dung spec
    -- ("VGP-U" + 5 chu so, xem generate_vgp_mock.py).
    unit_code,
    project_key,
    zone_key,
    unit_type,
    bedroom_count,
    bathroom_count,
    net_area_m2,
    gross_area_m2,
    floor_number,
    floor_band,
    balcony_orientation,
    door_orientation,
    view_primary_type,
    is_corner_unit,
    efficiency_ratio,
    distance_to_trash_room_m,
    is_adjacent_elevator,
    dark_bedroom_count,
    west_facing_exposure_pct,
    view_obstruction_distance_m,
    taboo_view_type,
    is_taboo_floor
from '../data/06_dim_unit_master.csv'
  );
