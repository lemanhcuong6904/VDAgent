select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

with child as (
    select channel_key as from_field
    from "vgp"."main_staging"."stg_fact_funnel_attribution"
    where channel_key is not null
),

parent as (
    select channel_key as to_field
    from "vgp"."main_staging"."stg_dim_sales_channel"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null



      
    ) dbt_internal_test