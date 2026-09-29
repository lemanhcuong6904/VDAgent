
    
    

with child as (
    select funnel_event_id as from_field
    from "vgp"."main_staging"."stg_fact_funnel_attribution"
    where funnel_event_id is not null
),

parent as (
    select funnel_event_id as to_field
    from "vgp"."main_staging"."stg_fact_sales_funnel_daily"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


