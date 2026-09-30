select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select attribution_id
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where attribution_id is null



      
    ) dbt_internal_test