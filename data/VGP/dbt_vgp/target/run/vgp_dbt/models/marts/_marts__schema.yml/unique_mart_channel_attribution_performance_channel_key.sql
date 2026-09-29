select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    channel_key as unique_field,
    count(*) as n_records

from "vgp"."main_marts"."mart_channel_attribution_performance"
where channel_key is not null
group by channel_key
having count(*) > 1



      
    ) dbt_internal_test