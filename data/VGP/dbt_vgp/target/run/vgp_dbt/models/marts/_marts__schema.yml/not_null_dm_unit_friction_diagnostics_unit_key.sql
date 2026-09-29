select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select unit_key
from "vgp"."main_marts"."dm_unit_friction_diagnostics"
where unit_key is null



      
    ) dbt_internal_test