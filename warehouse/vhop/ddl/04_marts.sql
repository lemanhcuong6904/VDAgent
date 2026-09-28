-- ddl/04_marts.sql
-- Tầng Serving Marts: chẩn đoán ma sát tồn kho cấp căn hộ và bảng bridge nguyên nhân.

-- Chẩn đoán ma sát: chỉ gồm căn AVAILABLE có DOM vượt ngưỡng quá hạn.
-- Ngưỡng phạm vi do `semantic_config.overdue_threshold_days` quy định và được
-- engine chẩn đoán + rule DQ (`x:diag_scope_*`) thực thi; DDL chỉ bảo đảm DOM
-- dương để không khoá cứng một hằng số lệch với cấu hình.
CREATE TABLE IF NOT EXISTS dm_unit_friction_diagnostics (
    diagnostic_id            VARCHAR(64) PRIMARY KEY,
    snapshot_date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    unit_key                 BIGINT NOT NULL REFERENCES dim_unit_master(unit_key),
    unit_code                VARCHAR(32) NOT NULL,
    project_name             VARCHAR(128) NOT NULL,
    zone_name                VARCHAR(64) NOT NULL,
    unsold_days_dom          INTEGER NOT NULL CHECK (unsold_days_dom > 0),
    price_spread_vs_peer_pct DECIMAL(5,2),
    ticket_size_vs_income_ratio DECIMAL(4,1),
    physical_defect_penalty  SMALLINT NOT NULL CHECK (physical_defect_penalty BETWEEN 0 AND 100),
    thermal_view_penalty     SMALLINT NOT NULL CHECK (thermal_view_penalty BETWEEN 0 AND 100),
    secondary_price_gap_pct  DECIMAL(5,2),
    funnel_dropoff_rate_pct  DECIMAL(5,2),
    primary_cause_code       VARCHAR(32) NOT NULL,
    recommended_action       VARCHAR(64) NOT NULL,
    -- Mở rộng theo spec §4.1/D8: cờ mẫu peer bị hạn chế và số peer thực tế.
    is_peer_sample_constrained BOOLEAN,
    peer_count               INTEGER,
    UNIQUE (snapshot_date_key, unit_key)
);

-- Bridge nguyên nhân chẩn đoán: nhiều nguyên nhân trên mỗi chẩn đoán.
CREATE TABLE IF NOT EXISTS unit_diagnostic_causes (
    diagnostic_id      VARCHAR(64) NOT NULL
                       REFERENCES dm_unit_friction_diagnostics(diagnostic_id),
    cause_code         VARCHAR(32) NOT NULL,
    unit_key           BIGINT NOT NULL REFERENCES dim_unit_master(unit_key),
    snapshot_date_key  INTEGER NOT NULL REFERENCES dim_date(date_key),
    severity_rank      SMALLINT NOT NULL CHECK (severity_rank >= 1),
    attribution_score  DECIMAL(4,3) NOT NULL CHECK (attribution_score > 0 AND attribution_score <= 1),
    evidence_artifact_id VARCHAR(64),
    PRIMARY KEY (diagnostic_id, cause_code)
);
