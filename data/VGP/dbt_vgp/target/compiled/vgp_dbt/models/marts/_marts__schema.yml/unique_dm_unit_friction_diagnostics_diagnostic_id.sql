
    
    

select
    diagnostic_id as unique_field,
    count(*) as n_records

from "vgp"."main_marts"."dm_unit_friction_diagnostics"
where diagnostic_id is not null
group by diagnostic_id
having count(*) > 1


