select channel_key, channel_id, channel_name, channel_tier, active_brokers_count
from {{ source('raw', 'dim_sales_channel') }}
