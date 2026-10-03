# Central Data Warehouse — PostgreSQL Backup (bàn giao team khác)

Bản dump PostgreSQL của **Central Master Dataset** (schema `gold`, 16 bảng) tại snapshot
đóng băng **2026-06-30**, dataset_version **3.1.0**. Dùng bản này thay cho CSV: team khác
`pg_restore` là có ngay warehouse để query, không cần tự dựng.

> **Trạng thái (2026-10-04, Phase 2):** production đọc **AWS RDS `cdw`** (schema `gold`, view `re` từ
> `docker/warehouse/canonical_views.sql`), khớp dump này ở các điểm đã kiểm read-only (snapshot `SNAP-20260630-01`
> APPROVED, semantic `3.1.0`, 47.713 căn trong `re.dim_unit_master`). `cdw_gold_snapshot_20260630.dump` là **artifact DR chuẩn** duy nhất: dùng để dựng lại kho
> khi mất AWS hoặc để chạy kho thật trên máy (README gốc, mục "Chưa có endpoint kho thật?").
> Pipeline CSV dựng ra dump (`warehouse/project_*`, `warehouse/dataset`, `organize_pack.py`, `assemble_dataset.py`,
> `verify_warehouse.py`, `build_backup.py`) và bản plain SQL trùng lặp đã được **retire**; dump không tái tạo lại
> từ CSV trong repo nữa (lịch sử Git vẫn giữ các file đó, commit `6857ea4`).

## Artifact

| File | Định dạng | Dùng với | Kích thước |
|---|---|---|---|
| `cdw_gold_snapshot_20260630.dump` | pg_dump custom (`-Fc`) — **artifact DR chuẩn** | `pg_restore` | ~3.9 MB |
| `schema_backup.sql` | DDL 16 bảng (đã nới, xem §Sai lệch) | tham chiếu | — |
| `load_pg.sql` | thứ tự nạp FK (nạp từ thư mục CSV stage của pipeline đã retire; chỉ còn để tham chiếu) | tham chiếu | — |

Nội dung schema `gold` (16 bảng): shared (snapshot_manifest, semantic_config, dim_date) +
6 dimension + 5 fact + Mart `dm_unit_friction_diagnostics` (5.051) + Bridge
`unit_diagnostic_causes` (10.797). `dim_unit_master`=47.713, `fact_unit_inventory_snapshot`=47.522.

## Khôi phục

```bash
# Vào DB rỗng đã tạo sẵn
createdb cdw
pg_restore -U <user> -d cdw --no-owner cdw_gold_snapshot_20260630.dump
#   xong: các bảng nằm trong schema "gold" (SET search_path TO gold;)
# rồi tạo lớp đọc `re` + role read-only cho Backend: docker/warehouse/apply-views.sh
```

Kiểm nhanh sau restore:
```sql
SET search_path TO gold, public;
SELECT count(*) FROM dm_unit_friction_diagnostics;   -- 5051
SELECT count(*) FROM unit_diagnostic_causes;          -- 10797
```

## Bằng chứng 4 gate M4 (chạy trên DB đã nạp — PASS)

```sql
-- G1: Σ attribution_score = 1.000 mỗi diagnostic  -> 0 vi phạm
SELECT count(*) FROM (SELECT diagnostic_id FROM gold.unit_diagnostic_causes
  GROUP BY diagnostic_id HAVING ABS(SUM(attribution_score)-1) > 0.0001) x;              -- 0
-- G2: phủ 8/8 core cause                          -> 8
SELECT count(DISTINCT cause_code) FROM gold.unit_diagnostic_causes WHERE cause_code IN
 ('LEGAL_PERMIT_BARRIER','SEVERE_PHYSICAL_DEFECT','EXTREME_THERMAL_EXPOSURE','SECONDARY_ARBITRAGE',
  'LUMP_SUM_TICKET_BARRIER','OVERPRICED_VS_PEER','LOW_SALES_INCENTIVE','DEEP_FUNNEL_DROP_OFF');   -- 8
-- G3: 0 UNEXPLAINED (AVAILABLE & DOM>90 mà không có diagnostic) -> 0
SELECT count(*) FROM gold.fact_unit_inventory_snapshot i WHERE i.inventory_status='AVAILABLE'
 AND i.unsold_days_dom>90 AND NOT EXISTS (SELECT 1 FROM gold.dm_unit_friction_diagnostics d
   WHERE d.unit_key=i.unit_key AND d.snapshot_date_key=i.snapshot_date_key);            -- 0
-- G4: snapshot_date_key toàn bộ = 20260630 (4 bảng có cột này); FK do DDL cưỡng chế khi nạp.
```

## Sai lệch so với `../schema_final_16_tables.sql` (canonical DDL)

Bản dump này nạp được dữ liệu THẬT bằng cách **nới DDL** (không sửa/không làm giả dữ liệu).
Mọi sai lệch đều bắt nguồn từ **project_300 (Vinhomes Grand Park, pipeline dbt)** không tuân
canonical DDL — cần chuyển M5 (DQ Gates) xử lý tại nguồn:

1. **Ép INT format float** `"N.0"→"N"` ở 9 cột (bug định dạng, không đổi ngữ nghĩa):
   `dim_zone_master.{total_floors,units_per_floor,passenger_elevators}`,
   `dim_infrastructure_assets.{original,revised}_completion_year`,
   `fact_unit_inventory_snapshot.spiff_bonus_vnd`, `fact_sales_channel_performance.avg_days_to_sell`,
   `dm_unit_friction_diagnostics.{physical_defect_penalty,thermal_view_penalty}` (347 dòng, từ VGP).
2. **`dim_date` mở rộng** 2025-01-01..2026-12-31 vì fact tham chiếu date_key ngoài dim_date
   canonical (funnel/price 2025, macro có cả 2025 và 2026-07/08).
3. **Nới enum CHECK**: `unit_type += 'DUPLEX'` (943 dòng VGP), `view_primary_type += 'INTERNAL_COURT'`
   (5.090 dòng VGP).
4. **Nới NOT NULL** `dim_zone_master.{units_per_floor,passenger_elevators,elevator_ratio}` cho 8 zone
   `LOW_RISE_VILLA` của VGP (villa không có thông số thang máy/căn-trên-sàn).
5. **Nới độ dài** `dm_unit_friction_diagnostics.recommended_action` VARCHAR(64)→(256) (VGP ghi mô tả
   dài tới ~118 ký tự).

> Lưu ý: `dim_unit_master`=47.713 (project_300 giữ nguyên ~33.6k unit theo quyết định lead —
> thoả invariant ≥3000). Đây là bản đóng băng single-snapshot; time-series gốc của VGP đã bị loại.

## Tái tạo

Không còn tái tạo từ CSV trong repo: pipeline `build_backup.py` ← `warehouse/dataset` đã retire ở Phase 2
(2026-10-04). Nếu cần dump mới, lấy từ kho chuẩn (AWS `cdw`, schema `gold`) bằng `pg_dump -n gold -Fc` với tài khoản
có quyền đọc `gold`, rồi thay file này trong một PR riêng có kiểm số dòng như trên.
