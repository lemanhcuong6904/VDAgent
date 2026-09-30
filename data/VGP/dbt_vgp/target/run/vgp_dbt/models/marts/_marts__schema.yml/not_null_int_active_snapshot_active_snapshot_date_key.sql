select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select active_snapshot_date_key
from "vgp"."main_marts"."int_active_snapshot"
where active_snapshot_date_key is null



      
    ) dbt_internal_test