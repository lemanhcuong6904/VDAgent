
  
  create view "vgp"."main_marts"."int_funnel_dropoff__dbt_tmp" as (
    

-- Ty le rut coc toan bo lich su (xap xi dung chung cho ca 6 ky, giong Python).
-- Chi tinh khi tong booking+cancel >= 3 (co mau toi thieu), khong thi de NULL.

select
    unit_key,
    sum(booking_reservations) as total_bookings,
    sum(booking_cancellations) as total_cancellations,
    case
        when sum(booking_reservations) + sum(booking_cancellations) >= 3
        then round(100.0 * sum(booking_cancellations) / (sum(booking_reservations) + sum(booking_cancellations)), 2)
        else null
    end as funnel_dropoff_rate_pct
from "vgp"."main_staging"."stg_fact_sales_funnel_daily"
group by 1
  );
