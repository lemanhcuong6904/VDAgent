-- ddl/06_indexes.sql
-- Index tối ưu truy vấn phân tích. Chạy sau cùng khi mọi bảng đã tồn tại.
CREATE INDEX IF NOT EXISTS ix_zone_project ON dim_zone_master (project_key);
CREATE INDEX IF NOT EXISTS ix_unit_project_zone ON dim_unit_master (project_key, zone_key);
CREATE INDEX IF NOT EXISTS ix_unit_type_band ON dim_unit_master (unit_type, floor_band);
CREATE INDEX IF NOT EXISTS ix_unit_net_area ON dim_unit_master (net_area_m2);
CREATE INDEX IF NOT EXISTS ix_inv_snapshot ON fact_unit_inventory_snapshot (snapshot_date_key);
CREATE INDEX IF NOT EXISTS ix_inv_available ON fact_unit_inventory_snapshot (snapshot_date_key)
    WHERE inventory_status = 'AVAILABLE';
CREATE INDEX IF NOT EXISTS ix_inv_batch ON fact_unit_inventory_snapshot (launch_batch_id);
CREATE INDEX IF NOT EXISTS ix_funnel_unit_date ON fact_sales_funnel_daily (unit_key, date_key);
CREATE INDEX IF NOT EXISTS ix_price_unit_date ON fact_unit_price_history (unit_key, effective_date_key);
CREATE INDEX IF NOT EXISTS ix_comp_match ON dim_secondary_market_comps
    (unit_type, floor_band, balcony_orientation, recorded_resale_date);
CREATE INDEX IF NOT EXISTS ix_diag_primary ON dm_unit_friction_diagnostics (primary_cause_code);
CREATE INDEX IF NOT EXISTS ix_diag_unit ON dm_unit_friction_diagnostics (unit_key);
CREATE INDEX IF NOT EXISTS ix_cause_code ON unit_diagnostic_causes (cause_code);
CREATE INDEX IF NOT EXISTS ix_cause_unit ON unit_diagnostic_causes (unit_key);
CREATE INDEX IF NOT EXISTS ix_showing_unit ON unit_showing_logs (unit_id);
CREATE INDEX IF NOT EXISTS ix_objection_unit ON unit_objections (unit_id);
CREATE INDEX IF NOT EXISTS ix_policy_unit ON unit_policy_adjustments (unit_id);
