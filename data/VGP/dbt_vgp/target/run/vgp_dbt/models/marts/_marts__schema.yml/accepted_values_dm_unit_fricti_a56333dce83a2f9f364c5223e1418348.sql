select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

with all_values as (

    select
        primary_cause_code as value_field,
        count(*) as n_records

    from "vgp"."main_marts"."dm_unit_friction_diagnostics"
    group by primary_cause_code

)

select *
from all_values
where value_field not in (
    'LEGAL_PERMIT_BARRIER','SEVERE_PHYSICAL_DEFECT','EXTREME_THERMAL_EXPOSURE','SECONDARY_ARBITRAGE','LUMP_SUM_TICKET_BARRIER','OVERPRICED_VS_PEER','LOW_SALES_INCENTIVE','DEEP_FUNNEL_DROP_OFF','MULTI_FACTOR_UNCLASSIFIED'
)



      
    ) dbt_internal_test