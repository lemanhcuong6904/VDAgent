{{ config(materialized='view') }}

-- Helper 1 dong: xac dinh ky snapshot ACTIVE (chinh thuc dung de bao cao) tu
-- snapshot_manifest.is_active - nguon duy nhat cho khai niem "active", KHONG
-- hardcode ngay o bat ky model/query nao khac. Khac voi ky moi NAP gan nhat
-- (MAX(snapshot_date) trong fact_unit_inventory_snapshot).

select
    snapshot_id as active_snapshot_id,
    snapshot_date as active_snapshot_date,
    cast(replace(cast(snapshot_date as varchar), '-', '') as integer) as active_snapshot_date_key
from {{ ref('stg_snapshot_manifest') }}
where is_active
