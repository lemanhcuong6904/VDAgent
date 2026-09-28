-- ddl/01_meta.sql
CREATE TABLE IF NOT EXISTS snapshot_manifest (
    snapshot_id      VARCHAR(64)  PRIMARY KEY,
    dataset_id       VARCHAR(64)  NOT NULL,
    dataset_version  VARCHAR(16)  NOT NULL,
    semantic_version VARCHAR(16)  NOT NULL,
    snapshot_date    DATE         NOT NULL,
    timezone         VARCHAR(32)  NOT NULL,
    currency         VARCHAR(8)   NOT NULL,
    price_basis      VARCHAR(32)  NOT NULL,
    area_basis       VARCHAR(32)  NOT NULL,
    source_system    VARCHAR(64)  NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_config (
    config_key       VARCHAR(64)  PRIMARY KEY,
    config_value     VARCHAR(256) NOT NULL,
    value_type       VARCHAR(16)  NOT NULL
                     CHECK (value_type IN ('INTEGER','DECIMAL','BOOLEAN','STRING')),
    semantic_version VARCHAR(16)  NOT NULL,
    approval_status  VARCHAR(16)  NOT NULL
                     CHECK (approval_status IN ('APPROVED','PENDING')),
    description      TEXT
);
