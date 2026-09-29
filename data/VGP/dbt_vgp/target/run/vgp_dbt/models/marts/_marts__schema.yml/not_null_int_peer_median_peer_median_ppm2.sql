select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select peer_median_ppm2
from "vgp"."main_marts"."int_peer_median"
where peer_median_ppm2 is null



      
    ) dbt_internal_test