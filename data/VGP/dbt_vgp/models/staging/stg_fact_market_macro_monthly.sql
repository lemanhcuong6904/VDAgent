select
    macro_record_id,
    date_key,
    market_id,
    segment,
    floating_mortgage_rate_pct,
    months_of_inventory_moi,
    absorption_rate_pct,
    median_household_income_vnd,
    macro_price_to_income_ratio
from {{ source('raw', 'fact_market_macro_monthly') }}
