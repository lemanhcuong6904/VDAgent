select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select bridge_id
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where bridge_id is null



      
    ) dbt_internal_test