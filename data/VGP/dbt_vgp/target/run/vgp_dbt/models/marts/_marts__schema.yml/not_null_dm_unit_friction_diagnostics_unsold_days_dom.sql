select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select unsold_days_dom
from "vgp"."main_marts"."dm_unit_friction_diagnostics"
where unsold_days_dom is null



      
    ) dbt_internal_test