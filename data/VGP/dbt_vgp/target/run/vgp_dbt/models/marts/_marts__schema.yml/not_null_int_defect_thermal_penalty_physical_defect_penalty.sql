select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select physical_defect_penalty
from "vgp"."main_marts"."int_defect_thermal_penalty"
where physical_defect_penalty is null



      
    ) dbt_internal_test