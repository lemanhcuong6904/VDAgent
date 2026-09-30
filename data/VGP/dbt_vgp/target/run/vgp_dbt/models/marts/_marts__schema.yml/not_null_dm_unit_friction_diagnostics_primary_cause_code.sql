select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select primary_cause_code
from "vgp"."main_marts"."dm_unit_friction_diagnostics"
where primary_cause_code is null



      
    ) dbt_internal_test