-- Moi can (unit_key) phai co DUNG 1 dong is_current=TRUE trong
-- bridge_unit_channel_history (dung 1 san dang phu trach hien tai - khong the
-- 0 hoac >=2 san cung "hien tai"). Test FAIL neu co unit_key vi pham.

select
    unit_key,
    count(*) as so_dong_current
from "vgp"."main_staging"."stg_bridge_unit_channel_history"
where is_current
group by unit_key
having count(*) != 1