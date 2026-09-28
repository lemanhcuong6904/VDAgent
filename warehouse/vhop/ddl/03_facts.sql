-- ddl/03_facts.sql
-- Tầng Facts & benchmarks — 6 bảng sự kiện/đo lường tham chiếu tới các dimension.

-- Ảnh chụp tồn kho theo ngày (fact grain: ngày chụp × căn hộ).
CREATE TABLE IF NOT EXISTS fact_unit_inventory_snapshot (
    snapshot_date_key   INTEGER NOT NULL REFERENCES dim_date(date_key),
    unit_key            BIGINT  NOT NULL REFERENCES dim_unit_master(unit_key),
    project_key         INTEGER NOT NULL REFERENCES dim_project_profile(project_key),
    zone_key            INTEGER NOT NULL REFERENCES dim_zone_master(zone_key),
    channel_key         INTEGER NOT NULL REFERENCES dim_sales_channel(channel_key),
    launch_batch_id     VARCHAR(32) NOT NULL,
    release_date        DATE NOT NULL,
    inventory_status    VARCHAR(16) NOT NULL
                        CHECK (inventory_status IN ('AVAILABLE','BOOKED','SOLD')),
    sold_date           DATE,
    unsold_days_dom     INTEGER NOT NULL CHECK (unsold_days_dom >= 0),
    is_overdue_flag     BOOLEAN NOT NULL,
    asking_price_vnd    BIGINT NOT NULL CHECK (asking_price_vnd > 0),
    discount_pct        DECIMAL(5,2) NOT NULL CHECK (discount_pct BETWEEN 0 AND 100),
    concession_value_vnd BIGINT NOT NULL CHECK (concession_value_vnd >= 0),
    net_price_vnd       BIGINT NOT NULL CHECK (net_price_vnd > 0),
    asking_price_per_m2 BIGINT NOT NULL CHECK (asking_price_per_m2 > 0),
    net_price_per_m2    BIGINT NOT NULL CHECK (net_price_per_m2 > 0),
    subsidy_duration_mo SMALLINT NOT NULL CHECK (subsidy_duration_mo >= 0),
    principal_grace_mo  SMALLINT NOT NULL CHECK (principal_grace_mo >= 0),
    base_commission_pct DECIMAL(4,2) NOT NULL CHECK (base_commission_pct BETWEEN 0 AND 100),
    spiff_bonus_vnd     BIGINT CHECK (spiff_bonus_vnd IS NULL OR spiff_bonus_vnd >= 0),
    is_exclusive_lock   BOOLEAN NOT NULL,
    PRIMARY KEY (snapshot_date_key, unit_key),
    CONSTRAINT ck_net_le_asking CHECK (net_price_vnd <= asking_price_vnd),
    CONSTRAINT ck_sold_date_null CHECK (inventory_status <> 'AVAILABLE' OR sold_date IS NULL),
    CONSTRAINT ck_sold_date_order CHECK (sold_date IS NULL OR sold_date >= release_date)
);

-- Phễu bán hàng theo ngày (một dòng sự kiện phễu cho mỗi căn hộ/ngày).
CREATE TABLE IF NOT EXISTS fact_sales_funnel_daily (
    funnel_event_id      BIGINT PRIMARY KEY,
    date_key             INTEGER NOT NULL REFERENCES dim_date(date_key),
    unit_key             BIGINT NOT NULL REFERENCES dim_unit_master(unit_key),
    web_listing_views    INTEGER NOT NULL CHECK (web_listing_views >= 0),
    inquiry_leads_count  SMALLINT NOT NULL CHECK (inquiry_leads_count >= 0),
    site_visits_count    SMALLINT NOT NULL CHECK (site_visits_count >= 0),
    booking_reservations SMALLINT NOT NULL CHECK (booking_reservations >= 0),
    booking_cancellations SMALLINT NOT NULL CHECK (booking_cancellations >= 0),
    cancellation_reason  VARCHAR(64),
    CONSTRAINT ck_cancel_le_booking CHECK (booking_cancellations <= booking_reservations)
);

-- Lịch sử điều chỉnh giá (một dòng cho mỗi lần đổi giá).
CREATE TABLE IF NOT EXISTS fact_unit_price_history (
    price_event_id       BIGINT PRIMARY KEY,
    unit_key             BIGINT NOT NULL REFERENCES dim_unit_master(unit_key),
    effective_date_key   INTEGER NOT NULL REFERENCES dim_date(date_key),
    old_asking_price_vnd BIGINT NOT NULL CHECK (old_asking_price_vnd > 0),
    new_asking_price_vnd BIGINT NOT NULL CHECK (new_asking_price_vnd > 0),
    price_change_pct     DECIMAL(5,2) NOT NULL,
    change_reason        VARCHAR(64)
);

-- Giao dịch thứ cấp so sánh (comps): tham chiếu dự án logic qua project_id.
CREATE TABLE IF NOT EXISTS dim_secondary_market_comps (
    comp_id               VARCHAR(32) PRIMARY KEY,
    project_id            VARCHAR(32) NOT NULL,
    unit_type             VARCHAR(16) NOT NULL,
    floor_band            VARCHAR(16) NOT NULL,
    balcony_orientation   VARCHAR(4) NOT NULL,
    recorded_resale_date  DATE NOT NULL,
    resale_price_per_m2_vnd BIGINT NOT NULL CHECK (resale_price_per_m2_vnd > 0),
    pink_book_status      VARCHAR(32) NOT NULL
                          CHECK (pink_book_status IN ('PINK_BOOK_AVAILABLE','SPA_ASSIGNMENT'))
);

-- Chỉ số vĩ mô theo tháng (duy nhất theo thị trường × phân khúc × ngày).
CREATE TABLE IF NOT EXISTS fact_market_macro_monthly (
    macro_record_id            VARCHAR(32) PRIMARY KEY,
    date_key                   INTEGER NOT NULL REFERENCES dim_date(date_key),
    market_id                  VARCHAR(32) NOT NULL,
    segment                    VARCHAR(32) NOT NULL,
    floating_mortgage_rate_pct DECIMAL(4,2) NOT NULL
                               CHECK (floating_mortgage_rate_pct BETWEEN 0 AND 100),
    months_of_inventory_moi    DECIMAL(4,1),
    absorption_rate_pct        DECIMAL(5,2) NOT NULL
                               CHECK (absorption_rate_pct BETWEEN 0 AND 100),
    median_household_income_vnd BIGINT NOT NULL CHECK (median_household_income_vnd > 0),
    macro_price_to_income_ratio DECIMAL(4,1),
    UNIQUE (market_id, segment, date_key)
);

-- Hiệu suất kênh bán theo ảnh chụp (PK composite ngày × kênh × dự án).
CREATE TABLE IF NOT EXISTS fact_sales_channel_performance (
    snapshot_date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    channel_key              INTEGER NOT NULL REFERENCES dim_sales_channel(channel_key),
    project_key              INTEGER NOT NULL REFERENCES dim_project_profile(project_key),
    assigned_units_count     INTEGER NOT NULL CHECK (assigned_units_count >= 0),
    sold_units_count         INTEGER NOT NULL CHECK (sold_units_count >= 0),
    absorption_rate_pct      DECIMAL(5,2) NOT NULL CHECK (absorption_rate_pct BETWEEN 0 AND 100),
    avg_days_to_sell         INTEGER,
    locked_inventory_over_90d INTEGER NOT NULL CHECK (locked_inventory_over_90d >= 0),
    PRIMARY KEY (snapshot_date_key, channel_key, project_key),
    CONSTRAINT ck_sold_le_assigned CHECK (sold_units_count <= assigned_units_count)
);
