
    
    

select
    unit_key as unique_field,
    count(*) as n_records

from "vgp"."main_marts"."int_defect_thermal_penalty"
where unit_key is not null
group by unit_key
having count(*) > 1


