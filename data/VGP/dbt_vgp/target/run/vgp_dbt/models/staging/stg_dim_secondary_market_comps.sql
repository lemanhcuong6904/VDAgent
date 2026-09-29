
  
  create view "vgp"."main_staging"."stg_dim_secondary_market_comps__dbt_tmp" as (
    select
    comp_id,
    project_id,
    -- Moi (mo rong): project_id gio la hang so "PRJ-VGP" (FK dung voi
    -- dim_project_profile 1 dong) - sub_project_id/sub_project_name giu phan
    -- biet phan khu nhu truoc.
    sub_project_id,
    sub_project_name,
    unit_type,
    floor_band,
    balcony_orientation,
    recorded_resale_date,
    resale_price_per_m2_vnd,
    pink_book_status
from '../data/12_dim_secondary_market_comps.csv'
  );
