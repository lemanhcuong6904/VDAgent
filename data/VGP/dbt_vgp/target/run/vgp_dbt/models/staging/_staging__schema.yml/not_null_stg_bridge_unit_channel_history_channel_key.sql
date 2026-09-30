select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select channel_key
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where channel_key is null



      
    ) dbt_internal_test