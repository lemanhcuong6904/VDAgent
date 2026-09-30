-- ============================================================
-- DDL 16 BẢNG - THEO ĐÚNG "Data_Warehouse_Schema (Final)" v3.1.0
-- Schema: gold
-- QUY TẮC KHÓA: mọi khóa thay thế (project_key, zone_key, unit_key, channel_key,
-- infra_key, funnel_event_id, price_event_id) là INTEGER/BIGINT thường, do NGƯỜI SINH
-- MOCK GÁN TRƯỚC theo dải số đã cấp (xem hướng dẫn). KHÔNG dùng SERIAL.
-- Người chạy file này: CHỈ 1 NGƯỜI (Data Lead), CHỈ 1 LẦN.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS gold;

-- ---------------- TẦNG 1: META ----------------
CREATE TABLE gold.snapshot_manifest (
    snapshot_id       VARCHAR(64)  PRIMARY KEY,
    dataset_id        VARCHAR(64)  NOT NULL,
    dataset_version   VARCHAR(16)  NOT NULL,
    semantic_version  VARCHAR(16)  NOT NULL,
    snapshot_date     DATE         NOT NULL,
    timezone          VARCHAR(32)  NOT NULL,
    currency          VARCHAR(8)   NOT NULL,
    price_basis       VARCHAR(32)  NOT NULL,
    area_basis        VARCHAR(32)  NOT NULL,
    source_system     VARCHAR(64)  NOT NULL
);

CREATE TABLE gold.semantic_config (
    config_key        VARCHAR(64)  PRIMARY KEY,
    config_value      VARCHAR(256) NOT NULL,
    value_type        VARCHAR(16)  NOT NULL CHECK (value_type IN ('INTEGER','DECIMAL','BOOLEAN','STRING')),
    semantic_version  VARCHAR(16)  NOT NULL,
    approval_status   VARCHAR(16)  NOT NULL CHECK (approval_status IN ('APPROVED','PENDING')),
    description       TEXT
);

-- ---------------- TẦNG 2: DIMENSION ----------------
CREATE TABLE gold.dim_date (
    date_key        INTEGER     PRIMARY KEY,
    full_date       DATE        NOT NULL UNIQUE,
    year            SMALLINT    NOT NULL,
    quarter         SMALLINT    NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month           SMALLINT    NOT NULL CHECK (month BETWEEN 1 AND 12),
    day_of_month    SMALLINT    NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    is_weekend      BOOLEAN     NOT NULL,
    fiscal_quarter  VARCHAR(8)  NOT NULL
);

CREATE TABLE gold.dim_project_profile (
    project_key                  INTEGER       PRIMARY KEY,
    project_id                   VARCHAR(32)   NOT NULL UNIQUE,
    project_name                 VARCHAR(128)  NOT NULL,
    market_id                    VARCHAR(32)   NOT NULL,
    market_name                  VARCHAR(64)   NOT NULL,
    province_city                VARCHAR(64)   NOT NULL,
    district                     VARCHAR(64)   NOT NULL,
    developer_name               VARCHAR(128)  NOT NULL,
    developer_tier               VARCHAR(16)   NOT NULL CHECK (developer_tier IN ('TIER_1','TIER_2','TIER_3')),
    developer_origin             VARCHAR(16)   NOT NULL CHECK (developer_origin IN ('DOMESTIC','FOREIGN_FDI')),
    segment                      VARCHAR(32)   NOT NULL CHECK (segment IN ('AFFORDABLE','MID','MID_HIGH','LUXURY')),
    construction_status          VARCHAR(32)   NOT NULL CHECK (construction_status IN ('FOUNDATION','SUPERSTRUCTURE','TOPPED_OUT','HANDED_OVER')),
    construction_progress_pct    DECIMAL(5,2)  NOT NULL CHECK (construction_progress_pct BETWEEN 0 AND 100),
    is_sales_permit_issued       BOOLEAN       NOT NULL,
    is_bank_guarantee_issued     BOOLEAN       NOT NULL,
    max_foreign_quota_exceeded   BOOLEAN       NOT NULL,
    primary_infra_id             VARCHAR(32),
    distance_to_primary_infra_m  INTEGER,
    partner_bank_name            VARCHAR(64),
    expected_handover_date       DATE
);

CREATE TABLE gold.dim_zone_master (
    zone_key             INTEGER      PRIMARY KEY,
    zone_id              VARCHAR(32)  NOT NULL UNIQUE,
    project_key          INTEGER      NOT NULL REFERENCES gold.dim_project_profile(project_key),
    zone_name            VARCHAR(64)  NOT NULL,
    zone_type            VARCHAR(32)  NOT NULL CHECK (zone_type IN ('HIGH_RISE_TOWER','LOW_RISE_VILLA','SHOPHOUSE')),
    total_floors         SMALLINT,
    basement_floors      SMALLINT,
    units_per_floor      SMALLINT,
    passenger_elevators  SMALLINT,
    elevator_ratio       DECIMAL(4,1),
    handover_standard    VARCHAR(32)  NOT NULL CHECK (handover_standard IN ('BARE_SHELL','BASIC_FINISH','FULLY_FURNISHED'))
);

CREATE TABLE gold.dim_unit_master (
    unit_key                     BIGINT        PRIMARY KEY,
    unit_id                      VARCHAR(32)   NOT NULL UNIQUE,
    unit_code                    VARCHAR(32)   NOT NULL,
    project_key                  INTEGER       NOT NULL REFERENCES gold.dim_project_profile(project_key),
    zone_key                     INTEGER       NOT NULL REFERENCES gold.dim_zone_master(zone_key),
    unit_type                    VARCHAR(16)   NOT NULL CHECK (unit_type IN ('STUDIO','1PN','2PN','3PN','4PN','PENTHOUSE','DUPLEX')),
    bedroom_count                SMALLINT      NOT NULL,
    bathroom_count               SMALLINT      NOT NULL,
    net_area_m2                  DECIMAL(8,2)  NOT NULL CHECK (net_area_m2 > 0),
    gross_area_m2                DECIMAL(8,2)  NOT NULL CHECK (gross_area_m2 > 0),
    floor_number                 SMALLINT      NOT NULL CHECK (floor_number >= 1),
    floor_band                   VARCHAR(16)   NOT NULL CHECK (floor_band IN ('LOW','MID','HIGH','TOP')),
    balcony_orientation          VARCHAR(4)    NOT NULL CHECK (balcony_orientation IN ('N','NE','E','SE','S','SW','W','NW')),
    door_orientation             VARCHAR(4)    CHECK (door_orientation IN ('N','NE','E','SE','S','SW','W','NW')),
    view_primary_type            VARCHAR(32)   NOT NULL CHECK (view_primary_type IN ('RIVER','PARK','POOL','CITY_OPEN','OBSTRUCTED','INTERNAL_COURT')),
    is_corner_unit               BOOLEAN       NOT NULL,
    efficiency_ratio             DECIMAL(4,3)  NOT NULL,
    distance_to_trash_room_m     DECIMAL(4,1),
    is_adjacent_elevator         BOOLEAN       NOT NULL,
    dark_bedroom_count           SMALLINT      NOT NULL,
    west_facing_exposure_pct     DECIMAL(4,2)  NOT NULL,
    view_obstruction_distance_m  DECIMAL(5,1),
    taboo_view_type              VARCHAR(32)   CHECK (taboo_view_type IN ('CEMETERY','WASTE_STATION','TEMPLE','NONE')),
    is_taboo_floor               BOOLEAN       NOT NULL,
    ext_attributes               JSONB,
    CONSTRAINT chk_gross_gt_net CHECK (gross_area_m2 > net_area_m2)
);

CREATE TABLE gold.dim_sales_channel (
    channel_key           INTEGER       PRIMARY KEY,
    channel_id            VARCHAR(32)   NOT NULL UNIQUE,
    channel_name          VARCHAR(128)  NOT NULL,
    channel_tier          VARCHAR(16)   NOT NULL CHECK (channel_tier IN ('TIER_1_EXCLUSIVE','TIER_2_GENERAL','INHOUSE')),
    active_brokers_count  INTEGER
);

CREATE TABLE gold.dim_infrastructure_assets (
    infra_key                  INTEGER       PRIMARY KEY,
    infra_id                   VARCHAR(32)   NOT NULL UNIQUE,
    infra_name                 VARCHAR(128)  NOT NULL,
    infra_type                 VARCHAR(32)   NOT NULL CHECK (infra_type IN ('URBAN_METRO','RING_ROAD','EXPRESSWAY','BRIDGE','AIRPORT')),
    lifecycle_stage            VARCHAR(32)   NOT NULL CHECK (lifecycle_stage IN ('PLANNING_APPROVED','UNDER_CONSTRUCTION','COMMERCIAL_OPERATION')),
    construction_progress_pct  DECIMAL(5,2),
    original_completion_year   SMALLINT,
    revised_completion_year    SMALLINT
);

CREATE TABLE gold.dim_secondary_market_comps (
    comp_id                  VARCHAR(32)  PRIMARY KEY,
    project_id               VARCHAR(32)  NOT NULL,
    unit_type                VARCHAR(16)  NOT NULL,
    floor_band               VARCHAR(16)  NOT NULL,
    balcony_orientation      VARCHAR(4)   NOT NULL,
    recorded_resale_date     DATE         NOT NULL,
    resale_price_per_m2_vnd  BIGINT       NOT NULL CHECK (resale_price_per_m2_vnd > 0),
    pink_book_status         VARCHAR(32)  NOT NULL CHECK (pink_book_status IN ('PINK_BOOK_AVAILABLE','SPA_ASSIGNMENT'))
);

-- ---------------- TẦNG 3: FACT ----------------
CREATE TABLE gold.fact_unit_inventory_snapshot (
    snapshot_date_key     INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    unit_key              BIGINT        NOT NULL REFERENCES gold.dim_unit_master(unit_key),
    project_key           INTEGER       NOT NULL REFERENCES gold.dim_project_profile(project_key),
    zone_key              INTEGER       NOT NULL REFERENCES gold.dim_zone_master(zone_key),
    channel_key           INTEGER       NOT NULL REFERENCES gold.dim_sales_channel(channel_key),
    launch_batch_id       VARCHAR(32)   NOT NULL,
    release_date          DATE          NOT NULL,
    inventory_status      VARCHAR(16)   NOT NULL CHECK (inventory_status IN ('AVAILABLE','BOOKED','SOLD')),
    sold_date             DATE,
    unsold_days_dom       INTEGER       NOT NULL,
    is_overdue_flag       BOOLEAN       NOT NULL,
    asking_price_vnd      BIGINT        NOT NULL CHECK (asking_price_vnd > 0),
    discount_pct          DECIMAL(5,2)  NOT NULL,
    concession_value_vnd  BIGINT        NOT NULL,
    net_price_vnd         BIGINT        NOT NULL CHECK (net_price_vnd > 0),
    asking_price_per_m2   BIGINT        NOT NULL,
    net_price_per_m2      BIGINT        NOT NULL,
    subsidy_duration_mo   SMALLINT      NOT NULL,
    principal_grace_mo    SMALLINT      NOT NULL,
    base_commission_pct   DECIMAL(4,2)  NOT NULL,
    spiff_bonus_vnd       BIGINT,
    is_exclusive_lock     BOOLEAN       NOT NULL,
    PRIMARY KEY (snapshot_date_key, unit_key),
    CONSTRAINT chk_net_le_asking CHECK (net_price_vnd <= asking_price_vnd),
    CONSTRAINT chk_sold_consistency CHECK (
        (inventory_status = 'SOLD' AND sold_date IS NOT NULL AND sold_date >= release_date)
        OR (inventory_status IN ('AVAILABLE','BOOKED') AND sold_date IS NULL)
    )
);
CREATE INDEX idx_fact_inv_project_date ON gold.fact_unit_inventory_snapshot (project_key, snapshot_date_key);
CREATE INDEX idx_fact_inv_zone_date    ON gold.fact_unit_inventory_snapshot (zone_key, snapshot_date_key);
CREATE INDEX idx_fact_inv_status       ON gold.fact_unit_inventory_snapshot (inventory_status);

CREATE TABLE gold.fact_sales_funnel_daily (
    funnel_event_id        BIGINT       PRIMARY KEY,
    date_key               INTEGER      NOT NULL REFERENCES gold.dim_date(date_key),
    unit_key               BIGINT       NOT NULL REFERENCES gold.dim_unit_master(unit_key),
    web_listing_views      INTEGER      NOT NULL,
    inquiry_leads_count    SMALLINT     NOT NULL,
    site_visits_count      SMALLINT     NOT NULL,
    booking_reservations   SMALLINT     NOT NULL,
    booking_cancellations  SMALLINT     NOT NULL,
    cancellation_reason    VARCHAR(64)  CHECK (cancellation_reason IN ('PRICE_TOO_HIGH','DEFECT_FOUND','LOAN_REJECTED')),
    CONSTRAINT chk_cancel_le_reserv CHECK (booking_cancellations <= booking_reservations)
);
CREATE INDEX idx_funnel_unit_date ON gold.fact_sales_funnel_daily (unit_key, date_key);

CREATE TABLE gold.fact_unit_price_history (
    price_event_id        BIGINT        PRIMARY KEY,
    unit_key              BIGINT        NOT NULL REFERENCES gold.dim_unit_master(unit_key),
    effective_date_key    INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    old_asking_price_vnd  BIGINT        NOT NULL,
    new_asking_price_vnd  BIGINT        NOT NULL,
    price_change_pct      DECIMAL(5,2)  NOT NULL,
    change_reason         VARCHAR(64)   CHECK (change_reason IN ('STIMULATE_SLOW_MOVING','MARKET_RALLY','CAMPAIGN'))
);
CREATE INDEX idx_price_hist_unit ON gold.fact_unit_price_history (unit_key, effective_date_key);

CREATE TABLE gold.fact_market_macro_monthly (
    macro_record_id              VARCHAR(32)   PRIMARY KEY,
    date_key                     INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    market_id                    VARCHAR(32)   NOT NULL,
    segment                      VARCHAR(32)   NOT NULL,
    floating_mortgage_rate_pct   DECIMAL(4,2)  NOT NULL,
    months_of_inventory_moi      DECIMAL(4,1),
    absorption_rate_pct          DECIMAL(5,2)  NOT NULL,
    median_household_income_vnd  BIGINT        NOT NULL,
    macro_price_to_income_ratio  DECIMAL(4,1)
);

CREATE TABLE gold.fact_sales_channel_performance (
    snapshot_date_key          INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    channel_key                INTEGER       NOT NULL REFERENCES gold.dim_sales_channel(channel_key),
    project_key                INTEGER       NOT NULL REFERENCES gold.dim_project_profile(project_key),
    assigned_units_count       INTEGER       NOT NULL,
    sold_units_count           INTEGER       NOT NULL,
    absorption_rate_pct        DECIMAL(5,2)  NOT NULL,
    avg_days_to_sell           INTEGER,
    locked_inventory_over_90d  INTEGER       NOT NULL,
    PRIMARY KEY (snapshot_date_key, channel_key, project_key)
);

-- ---------------- TẦNG 4: SERVING MART ----------------
CREATE TABLE gold.dm_unit_friction_diagnostics (
    diagnostic_id                VARCHAR(64)   PRIMARY KEY,
    snapshot_date_key            INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    unit_key                     BIGINT        NOT NULL REFERENCES gold.dim_unit_master(unit_key),
    unit_code                    VARCHAR(32)   NOT NULL,
    project_name                 VARCHAR(128)  NOT NULL,
    zone_name                    VARCHAR(64)   NOT NULL,
    unsold_days_dom              INTEGER       NOT NULL,
    price_spread_vs_peer_pct     DECIMAL(5,2),
    ticket_size_vs_income_ratio  DECIMAL(4,1),
    physical_defect_penalty      SMALLINT      NOT NULL CHECK (physical_defect_penalty BETWEEN 0 AND 100),
    thermal_view_penalty         SMALLINT      NOT NULL CHECK (thermal_view_penalty BETWEEN 0 AND 100),
    secondary_price_gap_pct      DECIMAL(5,2),
    funnel_dropoff_rate_pct      DECIMAL(5,2),
    primary_cause_code           VARCHAR(32)   NOT NULL,
    recommended_action           VARCHAR(256)   NOT NULL
);

CREATE TABLE gold.unit_diagnostic_causes (
    diagnostic_id         VARCHAR(64)   NOT NULL REFERENCES gold.dm_unit_friction_diagnostics(diagnostic_id),
    cause_code            VARCHAR(32)   NOT NULL,
    unit_key              BIGINT        NOT NULL REFERENCES gold.dim_unit_master(unit_key),
    snapshot_date_key     INTEGER       NOT NULL REFERENCES gold.dim_date(date_key),
    severity_rank         SMALLINT      NOT NULL CHECK (severity_rank BETWEEN 1 AND 3),
    attribution_score     DECIMAL(4,3)  NOT NULL,
    evidence_artifact_id  VARCHAR(64),
    PRIMARY KEY (diagnostic_id, cause_code)
);
