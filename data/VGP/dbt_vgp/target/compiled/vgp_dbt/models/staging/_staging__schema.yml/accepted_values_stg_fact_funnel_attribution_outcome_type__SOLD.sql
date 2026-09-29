
    
    

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


