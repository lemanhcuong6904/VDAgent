-- Run after 001_create_dw_v3_1_0.sql with psql -v ON_ERROR_STOP=1.
-- Temporary sample writes are rolled back; the warehouse remains empty.
BEGIN;

DO $verify$
DECLARE
    actual integer;
    rejected boolean;
BEGIN
    SELECT count(*) INTO actual FROM information_schema.tables
    WHERE table_schema = 'dw' AND table_type = 'BASE TABLE';
    IF actual <> 16 THEN RAISE EXCEPTION 'Expected 16 tables, found %', actual; END IF;

    SELECT count(*) INTO actual FROM information_schema.columns WHERE table_schema = 'dw';
    IF actual <> 178 THEN RAISE EXCEPTION 'Expected 178 columns, found %', actual; END IF;

    SELECT count(*) INTO actual FROM information_schema.columns
    WHERE table_schema = 'dw' AND is_nullable = 'NO';
    IF actual <> 150 THEN RAISE EXCEPTION 'Expected 150 NOT NULL columns, found %', actual; END IF;

    SELECT count(*) INTO actual FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'dw' AND c.contype = 'p';
    IF actual <> 16 THEN RAISE EXCEPTION 'Expected 16 PKs, found %', actual; END IF;

    SELECT count(*) INTO actual FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'dw' AND c.contype = 'f';
    IF actual <> 21 THEN RAISE EXCEPTION 'Expected 21 FKs, found %', actual; END IF;

    SELECT count(*) INTO actual FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'dw' AND c.contype = 'u';
    IF actual <> 9 THEN RAISE EXCEPTION 'Expected 9 UKs, found %', actual; END IF;

    SELECT count(*) INTO actual FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'dw' AND c.contype = 'c';
    IF actual <> 94 THEN RAISE EXCEPTION 'Expected 94 CHECKs, found %', actual; END IF;

    SELECT count(*) INTO actual FROM pg_indexes WHERE schemaname = 'dw';
    IF actual <> 41 THEN RAISE EXCEPTION 'Expected 41 indexes, found %', actual; END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'dw' AND c.conrelid = 'dw.fact_unit_inventory_snapshot'::regclass
          AND c.contype = 'c' AND pg_get_constraintdef(c.oid) LIKE '%net_price_vnd%asking_price_vnd%'
    ) THEN RAISE EXCEPTION 'Missing inventory price CHECK'; END IF;

    -- Valid date row, followed by invalid date key: CHECK must reject it.
    INSERT INTO dw.dim_date VALUES (20260630, DATE '2026-06-30', 2026, 2, 6, 30, FALSE, '2026-Q2');
    rejected := FALSE;
    BEGIN
        INSERT INTO dw.dim_date VALUES (20260701, DATE '2026-07-02', 2026, 3, 7, 2, FALSE, '2026-Q3');
    EXCEPTION WHEN check_violation THEN rejected := TRUE;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Invalid date key was accepted'; END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO dw.dim_date VALUES (20260630, DATE '2026-06-30', 2026, 2, 6, 30, FALSE, '2026-Q2');
    EXCEPTION WHEN unique_violation THEN rejected := TRUE;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Duplicate primary key was accepted'; END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO dw.semantic_config (config_key, config_value, value_type, semantic_version, approval_status)
        VALUES ('bad_type', '90', 'NUMBER', '3.1.0', 'APPROVED');
    EXCEPTION WHEN check_violation THEN rejected := TRUE;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Invalid enum was accepted'; END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO dw.semantic_config (config_key, config_value, value_type, semantic_version, approval_status)
        VALUES ('null_value', NULL, 'INTEGER', '3.1.0', 'APPROVED');
    EXCEPTION WHEN not_null_violation THEN rejected := TRUE;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'NULL in required column was accepted'; END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO dw.dim_zone_master
            (zone_id, project_key, zone_name, zone_type, units_per_floor,
             passenger_elevators, elevator_ratio, handover_standard)
        VALUES ('TEST-ZONE', 999999, 'Test zone', 'HIGH_RISE_TOWER', 12, 4, 3.0, 'BASIC_FINISH');
    EXCEPTION WHEN foreign_key_violation THEN rejected := TRUE;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Missing project FK was accepted'; END IF;

    RAISE NOTICE 'PASS: 16 tables, 178 columns (150 NOT NULL), 16 PK, 21 FK, 9 UK, 94 CHECK, 41 indexes; negative tests passed';
END
$verify$;

ROLLBACK;
