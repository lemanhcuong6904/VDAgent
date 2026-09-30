select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select outcome_date_key
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where outcome_date_key is null



      
    ) dbt_internal_test