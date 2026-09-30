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
from '../data/17_fact_funnel_attribution.csv'