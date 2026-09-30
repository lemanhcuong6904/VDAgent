select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select units_ever_assigned
from "vgp"."main_marts"."mart_channel_attribution_performance"
where units_ever_assigned is null



      
    ) dbt_internal_test