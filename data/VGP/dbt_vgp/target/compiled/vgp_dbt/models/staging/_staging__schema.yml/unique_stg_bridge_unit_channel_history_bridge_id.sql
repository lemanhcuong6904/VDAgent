
    
    

select
    bridge_id as unique_field,
    count(*) as n_records

from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where bridge_id is not null
group by bridge_id
having count(*) > 1


