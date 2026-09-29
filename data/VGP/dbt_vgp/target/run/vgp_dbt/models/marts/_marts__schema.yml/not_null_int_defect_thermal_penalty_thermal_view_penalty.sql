select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select thermal_view_penalty
from "vgp"."main_marts"."int_defect_thermal_penalty"
where thermal_view_penalty is null



      
    ) dbt_internal_test