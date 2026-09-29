
    
    

select
    snapshot_id as unique_field,
    count(*) as n_records

from "vgp"."main_staging"."stg_snapshot_manifest"
where snapshot_id is not null
group by snapshot_id
having count(*) > 1


