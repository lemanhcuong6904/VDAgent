-- ddl/05_crm.sql
-- Tầng CRM: người dùng và nhật ký tương tác bán hàng phục vụ phân tích objection.

-- Người dùng hệ thống (fixture bắt buộc cho các bảng CRM).
CREATE TABLE IF NOT EXISTS users (
    user_id    VARCHAR(64) PRIMARY KEY,
    username   VARCHAR(100) NOT NULL UNIQUE,
    email      VARCHAR(255) NOT NULL UNIQUE,
    full_name  VARCHAR(255) NOT NULL,
    role       VARCHAR(50) NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL
);

-- Nhật ký dẫn khách xem căn hộ.
CREATE TABLE IF NOT EXISTS unit_showing_logs (
    showing_id       VARCHAR(64) PRIMARY KEY,
    unit_id          VARCHAR(64) NOT NULL,
    agent_user_id    VARCHAR(64) NOT NULL REFERENCES users(user_id),
    showing_date     TIMESTAMPTZ NOT NULL,
    duration_minutes SMALLINT,
    customer_segment VARCHAR(50),
    interest_level   VARCHAR(20) NOT NULL,
    notes            TEXT
);

-- Ý kiến phản đối của khách hàng, có thể gắn với một buổi xem.
CREATE TABLE IF NOT EXISTS unit_objections (
    objection_id       VARCHAR(64) PRIMARY KEY,
    showing_id         VARCHAR(64) REFERENCES unit_showing_logs(showing_id),
    unit_id            VARCHAR(64) NOT NULL,
    objection_category VARCHAR(50) NOT NULL,
    specific_reason    TEXT NOT NULL,
    severity           VARCHAR(20) NOT NULL,
    competitor_alternative VARCHAR(255),
    created_at         TIMESTAMPTZ NOT NULL
);

-- Điều chỉnh chính sách bán hàng theo căn hộ (khoảng hiệu lực).
CREATE TABLE IF NOT EXISTS unit_policy_adjustments (
    adjustment_id      VARCHAR(64) PRIMARY KEY,
    unit_id            VARCHAR(64) NOT NULL,
    policy_type        VARCHAR(50) NOT NULL,
    policy_value_desc  VARCHAR(255) NOT NULL,
    effective_from     DATE NOT NULL,
    effective_to       DATE,
    dom_at_intervention SMALLINT,
    days_to_liquidation SMALLINT,
    is_liquidated      BOOLEAN NOT NULL DEFAULT FALSE,
    is_active          BOOLEAN NOT NULL,
    CONSTRAINT ck_policy_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
