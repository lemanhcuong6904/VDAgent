select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select diagnostic_id
from "vgp"."main_marts"."dm_unit_friction_diagnostics"
where diagnostic_id is null



      
    ) dbt_internal_test