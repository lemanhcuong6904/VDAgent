
  
  create view "vgp"."main_marts"."int_defect_thermal_penalty__dbt_tmp" as (
    

-- Diem phat khuyet tat vat ly + vi khi hau, dung nguyen nguong tu
-- generate_vgp_mock.py (DEFECT_TRASH_ROOM_HARD_M=3.0, SOFT_M=5.0,
-- DARK_BEDROOM_POINTS_PER=15, EFFICIENCY_HARD=0.75, SOFT=0.80,
-- THERMAL_WEST_EXPOSURE_HARD_PCT=0.50, SOFT_PCT=0.25, OBSTRUCTION_HARD_M=8.0)

select
    unit_key,

    least(100,
        case
            when distance_to_trash_room_m < 3.0 then 30
            when distance_to_trash_room_m < 5.0 then 15
            else 0
        end
        + case when is_adjacent_elevator then 25 else 0 end
        + least(40, dark_bedroom_count * 15)
        + case
            when efficiency_ratio < 0.75 then 20
            when efficiency_ratio < 0.80 then 10
            else 0
          end
    ) as physical_defect_penalty,

    least(100,
        case
            when balcony_orientation in ('W','SW','NW') and west_facing_exposure_pct >= 0.50 then 40
            when balcony_orientation in ('W','SW','NW') and west_facing_exposure_pct >= 0.25 then 20
            else 0
        end
        + case when view_primary_type = 'OBSTRUCTED' or view_obstruction_distance_m < 8.0 then 25 else 0 end
        + case when taboo_view_type != 'NONE' or is_taboo_floor then 30 else 0 end
    ) as thermal_view_penalty

from "vgp"."main_staging"."stg_dim_unit_master"
  );
