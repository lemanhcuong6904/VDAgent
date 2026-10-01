select
    funnel_event_id,
    date_key,
    unit_key,
    web_listing_views,
    inquiry_leads_count,
    site_visits_count,
    booking_reservations,
    booking_cancellations,
    cancellation_reason
from {{ source('raw', 'fact_sales_funnel_daily') }}
