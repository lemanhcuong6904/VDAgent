select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select attribution_model
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where attribution_model is null



      
    ) dbt_internal_test