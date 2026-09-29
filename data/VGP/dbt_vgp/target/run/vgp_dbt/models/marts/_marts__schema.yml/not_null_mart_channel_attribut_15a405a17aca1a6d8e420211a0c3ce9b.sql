select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select total_attribution_weight
from "vgp"."main_marts"."mart_channel_attribution_performance"
where total_attribution_weight is null



      
    ) dbt_internal_test