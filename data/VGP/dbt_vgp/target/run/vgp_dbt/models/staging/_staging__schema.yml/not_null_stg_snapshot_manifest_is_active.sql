select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select is_active
from "vgp"."main_staging"."stg_snapshot_manifest"
where is_active is null



      
    ) dbt_internal_test