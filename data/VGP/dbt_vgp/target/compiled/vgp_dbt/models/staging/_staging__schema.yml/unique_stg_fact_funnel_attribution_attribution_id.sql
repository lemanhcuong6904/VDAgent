
    
    

select
    attribution_id as unique_field,
    count(*) as n_records

from "vgp"."main_staging"."stg_fact_funnel_attribution"
where attribution_id is not null
group by attribution_id
having count(*) > 1


