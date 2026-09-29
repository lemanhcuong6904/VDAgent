select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      -- Phai co DUNG 1 kỳ snapshot duoc danh dau is_active=TRUE trong snapshot_manifest
-- (khong duoc 0 hoac >=2 kỳ "active" cung luc). Test FAIL neu tra ve dong (nghia
-- la so kỳ active != 1).

select count(*) as so_ky_active
from "vgp"."main_staging"."stg_snapshot_manifest"
where is_active
having count(*) != 1
      
    ) dbt_internal_test