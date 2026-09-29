select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select attribution_weight
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where attribution_weight is null



      
    ) dbt_internal_test