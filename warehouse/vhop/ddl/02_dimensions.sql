-- ddl/02_dimensions.sql
-- Tầng Dimensions (conformed dimensions) — 6 bảng nền tảng của data warehouse.
-- Khoá thay thế (surrogate key) là số nguyên tường minh, không dùng SERIAL/IDENTITY.

-- Lịch (date dimension): một dòng cho mỗi ngày, dùng làm FK thời gian cho mọi fact.
CREATE TABLE IF NOT EXISTS dim_date (
    date_key       INTEGER PRIMARY KEY,
    full_date      DATE NOT NULL UNIQUE,
    year           SMALLINT NOT NULL,
    quarter        SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month          SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    day_of_month   SMALLINT NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    is_weekend     BOOLEAN NOT NULL,
    fiscal_quarter VARCHAR(8) NOT NULL
);

-- Hồ sơ dự án: thuộc tính cấp dự án phục vụ phân tích thị trường và rủi ro pháp lý.
CREATE TABLE IF NOT EXISTS dim_project_profile (
    project_key                 INTEGER PRIMARY KEY,
    project_id                  VARCHAR(32) NOT NULL UNIQUE,
    project_name                VARCHAR(128) NOT NULL,
    market_id                   VARCHAR(32) NOT NULL,
    market_name                 VARCHAR(64) NOT NULL,
    province_city               VARCHAR(64) NOT NULL,
    district                    VARCHAR(64) NOT NULL,
    developer_name              VARCHAR(128) NOT NULL,
    developer_tier              VARCHAR(16) NOT NULL
                                CHECK (developer_tier IN ('TIER_1','TIER_2','TIER_3')),
    developer_origin            VARCHAR(16) NOT NULL
                                CHECK (developer_origin IN ('DOMESTIC','FOREIGN_FDI')),
    segment                     VARCHAR(32) NOT NULL
                                CHECK (segment IN ('AFFORDABLE','MID','MID_HIGH','LUXURY')),
    construction_status         VARCHAR(32) NOT NULL
                                CHECK (construction_status IN
                                       ('FOUNDATION','SUPERSTRUCTURE','TOPPED_OUT','HANDED_OVER')),
    construction_progress_pct   DECIMAL(5,2) NOT NULL
                                CHECK (construction_progress_pct BETWEEN 0 AND 100),
    is_sales_permit_issued      BOOLEAN NOT NULL,
    is_bank_guarantee_issued    BOOLEAN NOT NULL,
    max_foreign_quota_exceeded  BOOLEAN NOT NULL,
    primary_infra_id            VARCHAR(32),
    distance_to_primary_infra_m INTEGER,
    partner_bank_name           VARCHAR(64),
    expected_handover_date      DATE
);

-- Phân khu (zone): thuộc một dự án; chứa thông số toà nhà.
CREATE TABLE IF NOT EXISTS dim_zone_master (
    zone_key            INTEGER PRIMARY KEY,
    zone_id             VARCHAR(32) NOT NULL UNIQUE,
    project_key         INTEGER NOT NULL REFERENCES dim_project_profile(project_key),
    zone_name           VARCHAR(64) NOT NULL,
    zone_type           VARCHAR(32) NOT NULL
                        CHECK (zone_type IN ('HIGH_RISE_TOWER','LOW_RISE_VILLA','SHOPHOUSE')),
    total_floors        SMALLINT,
    basement_floors     SMALLINT,
    units_per_floor     SMALLINT NOT NULL,
    passenger_elevators SMALLINT NOT NULL CHECK (passenger_elevators > 0),
    elevator_ratio      DECIMAL(4,1) NOT NULL,
    handover_standard   VARCHAR(32) NOT NULL
                        CHECK (handover_standard IN ('BARE_SHELL','BASIC_FINISH','FULLY_FURNISHED'))
);

-- Căn hộ (unit): hạt nhân phân tích; mang nhiều thuộc tính vật lý và phong thuỷ.
CREATE TABLE IF NOT EXISTS dim_unit_master (
    unit_key                  BIGINT PRIMARY KEY,
    unit_id                   VARCHAR(32) NOT NULL UNIQUE,
    unit_code                 VARCHAR(32) NOT NULL,
    project_key               INTEGER NOT NULL REFERENCES dim_project_profile(project_key),
    zone_key                  INTEGER NOT NULL REFERENCES dim_zone_master(zone_key),
    unit_type                 VARCHAR(16) NOT NULL
                              CHECK (unit_type IN ('STUDIO','1PN','2PN','3PN','4PN','PENTHOUSE')),
    bedroom_count             SMALLINT NOT NULL CHECK (bedroom_count >= 0),
    bathroom_count            SMALLINT NOT NULL CHECK (bathroom_count >= 0),
    net_area_m2               DECIMAL(8,2) NOT NULL CHECK (net_area_m2 > 0),
    gross_area_m2             DECIMAL(8,2) NOT NULL CHECK (gross_area_m2 > 0),
    floor_number              SMALLINT NOT NULL CHECK (floor_number >= 1),
    floor_band                VARCHAR(16) NOT NULL
                              CHECK (floor_band IN ('LOW','MID','HIGH','TOP')),
    balcony_orientation       VARCHAR(4) NOT NULL
                              CHECK (balcony_orientation IN ('N','NE','E','SE','S','SW','W','NW')),
    door_orientation          VARCHAR(4),
    view_primary_type         VARCHAR(32) NOT NULL
                              CHECK (view_primary_type IN ('RIVER','PARK','POOL','CITY_OPEN','OBSTRUCTED')),
    is_corner_unit            BOOLEAN NOT NULL,
    efficiency_ratio          DECIMAL(4,3) NOT NULL CHECK (efficiency_ratio > 0 AND efficiency_ratio <= 1),
    distance_to_trash_room_m  DECIMAL(4,1),
    is_adjacent_elevator      BOOLEAN NOT NULL,
    dark_bedroom_count        SMALLINT NOT NULL CHECK (dark_bedroom_count >= 0),
    west_facing_exposure_pct  DECIMAL(4,2) NOT NULL
                              CHECK (west_facing_exposure_pct BETWEEN 0 AND 100),
    view_obstruction_distance_m DECIMAL(5,1),
    taboo_view_type           VARCHAR(32)
                              CHECK (taboo_view_type IS NULL OR
                                     taboo_view_type IN ('CEMETERY','WASTE_STATION','TEMPLE','NONE')),
    is_taboo_floor            BOOLEAN NOT NULL,
    ext_attributes            JSONB,
    CONSTRAINT ck_unit_area_order CHECK (net_area_m2 <= gross_area_m2)
);

-- Kênh bán hàng: phân cấp đại lý độc quyền / đại lý chung / in-house.
CREATE TABLE IF NOT EXISTS dim_sales_channel (
    channel_key          INTEGER PRIMARY KEY,
    channel_id           VARCHAR(32) NOT NULL UNIQUE,
    channel_name         VARCHAR(128) NOT NULL,
    channel_tier         VARCHAR(16) NOT NULL
                         CHECK (channel_tier IN ('TIER_1_EXCLUSIVE','TIER_2_GENERAL','INHOUSE')),
    active_brokers_count INTEGER
);

-- Hạ tầng trọng điểm: vòng đời và tiến độ phục vụ định giá.
CREATE TABLE IF NOT EXISTS dim_infrastructure_assets (
    infra_key                  INTEGER PRIMARY KEY,
    infra_id                   VARCHAR(32) NOT NULL UNIQUE,
    infra_name                 VARCHAR(128) NOT NULL,
    infra_type                 VARCHAR(32) NOT NULL
                               CHECK (infra_type IN ('URBAN_METRO','RING_ROAD','EXPRESSWAY','BRIDGE','AIRPORT')),
    lifecycle_stage            VARCHAR(32) NOT NULL
                               CHECK (lifecycle_stage IN
                                      ('PLANNING_APPROVED','UNDER_CONSTRUCTION','COMMERCIAL_OPERATION')),
    construction_progress_pct  DECIMAL(5,2),
    original_completion_year   SMALLINT,
    revised_completion_year    SMALLINT
);
