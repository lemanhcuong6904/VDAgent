
    
    

with all_values as (

    select
        attribution_model as value_field,
        count(*) as n_records

    from "vgp"."main_staging"."stg_fact_funnel_attribution"
    group by attribution_model

)

select *
from all_values
where value_field not in (
    'LINEAR'
)


