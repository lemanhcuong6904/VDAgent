-- load.sql — Nạp Central Master Dataset (16 bảng) vào PostgreSQL schema `gold`.
-- Chạy từ chính thư mục này:  psql -d <db> -f load.sql
-- DDL: ../schema_final_16_tables.sql (tạo schema gold + 16 bảng + khóa ngoại).
--
-- THỨ TỰ NẠP tuân thủ khóa ngoại (FK): shared → conformed dims → facts →
-- MART (dm_unit_friction_diagnostics) → BRIDGE (unit_diagnostic_causes).
-- Mart/Bridge nạp SAU dims/facts vì tham chiếu dim_date, dim_unit_master và
-- (bridge) dm_unit_friction_diagnostics.
SET search_path TO gold, public;

-- 1) Shared / manifest (không FK)
\copy snapshot_manifest        FROM 'snapshot_manifest.csv'        WITH (FORMAT csv, HEADER true)
\copy semantic_config          FROM 'semantic_config.csv'          WITH (FORMAT csv, HEADER true)
\copy dim_date                 FROM 'dim_date.csv'                 WITH (FORMAT csv, HEADER true)

-- 2) Conformed dimensions (dim_unit_master phụ thuộc project + zone)
\copy dim_project_profile      FROM 'dim_project_profile.csv'      WITH (FORMAT csv, HEADER true)
\copy dim_zone_master          FROM 'dim_zone_master.csv'          WITH (FORMAT csv, HEADER true)
\copy dim_unit_master          FROM 'dim_unit_master.csv'          WITH (FORMAT csv, HEADER true)
\copy dim_sales_channel        FROM 'dim_sales_channel.csv'        WITH (FORMAT csv, HEADER true)
\copy dim_infrastructure_assets FROM 'dim_infrastructure_assets.csv' WITH (FORMAT csv, HEADER true)
\copy dim_secondary_market_comps FROM 'dim_secondary_market_comps.csv' WITH (FORMAT csv, HEADER true)

-- 3) Facts (tham chiếu dims)
\copy fact_unit_inventory_snapshot    FROM 'fact_unit_inventory_snapshot.csv'    WITH (FORMAT csv, HEADER true)
\copy fact_sales_funnel_daily         FROM 'fact_sales_funnel_daily.csv'         WITH (FORMAT csv, HEADER true)
\copy fact_unit_price_history         FROM 'fact_unit_price_history.csv'         WITH (FORMAT csv, HEADER true)
\copy fact_market_macro_monthly       FROM 'fact_market_macro_monthly.csv'       WITH (FORMAT csv, HEADER true)
\copy fact_sales_channel_performance  FROM 'fact_sales_channel_performance.csv'  WITH (FORMAT csv, HEADER true)

-- 4) Serving Mart + Bridge chẩn đoán (nạp SAU cùng)
\copy dm_unit_friction_diagnostics    FROM 'dm_unit_friction_diagnostics.csv'    WITH (FORMAT csv, HEADER true)
\copy unit_diagnostic_causes          FROM 'unit_diagnostic_causes.csv'          WITH (FORMAT csv, HEADER true)
