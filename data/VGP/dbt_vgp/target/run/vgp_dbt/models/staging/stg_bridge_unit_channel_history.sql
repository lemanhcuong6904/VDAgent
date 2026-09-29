
  
  create view "vgp"."main_staging"."stg_bridge_unit_channel_history__dbt_tmp" as (
    select
    bridge_id,
    unit_key,
    channel_key,
    valid_from_date_key,
    valid_to_date_key,
    is_current,
    assignment_type
from '../data/16_bridge_unit_channel_history.csv'
  );
