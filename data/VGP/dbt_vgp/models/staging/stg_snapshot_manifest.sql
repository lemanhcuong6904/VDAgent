select
    snapshot_id,
    dataset_id,
    dataset_version,
    semantic_version,
    snapshot_date,
    timezone,
    currency,
    price_basis,
    area_basis,
    source_system,
    is_active
from {{ source('raw', 'snapshot_manifest') }}
