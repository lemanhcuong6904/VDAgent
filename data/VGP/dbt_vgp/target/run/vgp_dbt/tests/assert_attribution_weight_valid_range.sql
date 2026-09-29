select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      -- attribution_weight phai nam trong khoang hop le (0, 1] - mo hinh LINEAR chia
-- deu 1/so_touchpoint nen khong bao gio <=0 hoac >1. Test FAIL neu co dong vi pham.

select
    attribution_id,
    unit_key,
    attribution_weight
from "vgp"."main_staging"."stg_fact_funnel_attribution"
where attribution_weight <= 0 or attribution_weight > 1
      
    ) dbt_internal_test