-- Test doi chieu: ket qua chan doan tinh bang SQL/dbt (dm_unit_friction_diagnostics)
-- phai khop voi ket qua Python da tinh san (15_dm_unit_friction_diagnostics.csv,
-- source: dm_unit_friction_diagnostics_python). Test FAIL neu co dong lech nhau
-- (tra ve cac dong lech - dbt quy uoc: test fail khi co dong tra ve).

select
    py.snapshot_date_key,
    py.unit_key,
    py.unit_code,
    py.primary_cause_code as python_cause,
    dbt.primary_cause_code as dbt_cause
from '../data/15_dm_unit_friction_diagnostics.csv' py
join "vgp"."main_marts"."dm_unit_friction_diagnostics" dbt
    on py.snapshot_date_key = dbt.snapshot_date_key and py.unit_key = dbt.unit_key
where py.primary_cause_code != dbt.primary_cause_code