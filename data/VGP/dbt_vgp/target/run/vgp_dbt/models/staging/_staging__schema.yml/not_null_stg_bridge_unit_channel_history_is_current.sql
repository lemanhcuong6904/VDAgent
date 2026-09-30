select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select is_current
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where is_current is null



      
    ) dbt_internal_test