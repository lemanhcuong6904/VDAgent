
    
    

with all_values as (

    select
        assignment_type as value_field,
        count(*) as n_records

    from "vgp"."main_staging"."stg_bridge_unit_channel_history"
    group by assignment_type

)

select *
from all_values
where value_field not in (
    'EXCLUSIVE','CO_LISTING'
)


