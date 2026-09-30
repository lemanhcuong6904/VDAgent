select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select outcome_type
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where outcome_type is null



      
    ) dbt_internal_test