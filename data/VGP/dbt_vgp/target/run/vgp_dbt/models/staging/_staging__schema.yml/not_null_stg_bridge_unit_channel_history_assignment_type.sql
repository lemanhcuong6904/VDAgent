select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select assignment_type
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where assignment_type is null



      
    ) dbt_internal_test