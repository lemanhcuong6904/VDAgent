select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select unit_key
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where unit_key is null



      
    ) dbt_internal_test