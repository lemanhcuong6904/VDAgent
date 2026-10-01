select
    bridge_id,
    unit_key,
    channel_key,
    valid_from_date_key,
    valid_to_date_key,
    is_current,
    assignment_type
from {{ source('raw', 'bridge_unit_channel_history') }}
