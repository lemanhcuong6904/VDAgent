select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

with all_values as (

    select
        outcome_type as value_field,
        count(*) as n_records

    from "vgp"."main_staging"."stg_fact_funnel_attribution"
    group by outcome_type

)

select *
from all_values
where value_field not in (
    'SOLD'
)



      
    ) dbt_internal_test