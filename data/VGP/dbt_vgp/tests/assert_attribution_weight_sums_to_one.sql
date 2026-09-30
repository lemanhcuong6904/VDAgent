-- Voi moi (unit_key, outcome_date_key) da chuyen doi, tong attribution_weight
-- cua tat ca touchpoint duoc gan cong phai xap xi 1.0 (dung quy tac mo hinh
-- LINEAR: chia deu 100% cong cho cac touchpoint dan toi 1 outcome). Dung nguong
-- sai so 0.01 de chap nhan sai so lam tron 4 chu so thap phan khi sinh du lieu.
-- Test FAIL neu co (unit_key, outcome_date_key) nao tong weight lech > 0.01.

select
    unit_key,
    outcome_date_key,
    outcome_type,
    round(sum(attribution_weight), 4) as total_weight
from {{ ref('stg_fact_funnel_attribution') }}
group by unit_key, outcome_date_key, outcome_type
having abs(sum(attribution_weight) - 1.0) > 0.01
