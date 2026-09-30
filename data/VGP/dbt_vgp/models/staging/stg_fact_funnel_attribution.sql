select
    attribution_id,
    funnel_event_id,
    unit_key,
    channel_key,
    touchpoint_date_key,
    attribution_model,
    attribution_weight,
    outcome_type,
    outcome_date_key
from {{ source('raw', 'fact_funnel_attribution') }}
