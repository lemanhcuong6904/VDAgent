# Hướng dẫn Tích hợp & Gom Dataset Central Data Warehouse (assemble_dataset & premerge_validate)

**Ngày cập nhật:** 2026-09-30  
**Người thực hiện:** Nguyễn Tuấn Anh  
**Nhánh làm việc & Push:** `DATA` (`origin/DATA`)  
**Tài liệu liên quan:** `docs/WAREHOUSE_INTEGRATION_CONTEXT.md`, `docs/GIT_WAREHOUSE_INTEGRATION_RULES.md`, `warehouse/id_registry.json`

---

## 1. Bối cảnh & Kết quả Tích hợp 5 Project Packs (Đã hoàn tất)

Trước khi thực hiện task gom Dataset, 5 pack dữ liệu từ 5 thành viên đã được tích hợp, re-key chuẩn hóa theo `id_registry.json` v3.1.1, kiểm tra đạt 100% Quality Gate và push thành công lên nhánh **`DATA`**:

### 📊 Bảng tổng hợp 5 Pack dữ liệu nguồn & Canonical Warehouse

| Project | Tên dự án | Phụ trách nguồn | Nguồn CSV Raw | Thư mục Canonical | Trạng thái Quality Gate |
|:---:|---|---|---|---|:---:|
| **100** | Vinhomes Ocean Park | Xuân Dũng | `data/project_100/` | `warehouse/project_100/` | **PASS (13/13 bảng)** |
| **200** | Vinhomes Smart City | Nguyễn Quang Huy | `data/project_200/` | `warehouse/project_200/` | **PASS (13/13 bảng)** |
| **300** | Vinhomes Grand Park | Hà Duy Anh | `data/project_300/` | `warehouse/project_300/` | **PASS (13/13 bảng)** |
| **400** | Masteri Centre Point | Nguyễn Tuấn Anh | `data/masteri_cp/csv/` | `warehouse/project_400/` | **PASS (13/13 bảng)** |
| **500** | Phú Mỹ (Risk Project) | Nguyễn Mai Huy | `data/risk_project_mock/csv/` | `warehouse/project_500/` | **PASS (13/13 bảng)** |

### 📝 Các Commit đã Push lên nhánh `DATA` (`origin/DATA`)
1. `2eb2c62` `feat(data): add project 400 mock source pack`
2. `7ee6a78` `feat(data): add project 500 mock source pack`
3. `a5a66be` `feat(warehouse): integrate project 400 canonical pack`
4. `45ac5f3` `feat(warehouse): integrate project 500 canonical pack`
5. `62c4c12` `fix(warehouse): normalize project 300 funnel data and adapter`

---

## 2. Mục tiêu Task: `assemble_dataset` & `premerge_validate`

### 🎯 Nhiệm vụ chính
1. **`premerge_validate`**: Thực hiện kiểm tra tiền hợp nhất (Pre-Merge Sanity & Integrity Validation) toàn diện trên cả 5 pack dữ liệu và 3 bảng shared trước khi ghép.
2. **`assemble_dataset`**: Gom 13 bảng từ 5 pack dự án (`project_100` đến `project_500`) kết hợp với 3 bảng shared (`snapshot_manifest`, `semantic_config`, `dim_date`) thành **1 Central Master Dataset (16 bảng CSV duy nhất)** lưu tại `warehouse/dataset/`.
3. **`dataset_manifest.json`**: Tự động sinh file manifest chứa thông tin mã checksum SHA256, số lượng bản ghi và thông số kỹ thuật của Master Dataset để làm đầu vào cho Engine trung tâm (Mart + Bridge).

---

## 3. Quy trình & Tiêu chuẩn Kiểm tra (`premerge_validate`)

Trước khi ghép file, công cụ validation cần bảo đảm các tiêu chuẩn sau:

### 🔍 Check 1: Key Banding & ID Registry (v3.1.1)
- `unit_key`, `zone_key`, `channel_key`, `infra_key` của mỗi project phải nằm chính xác trong dải quy định tại `warehouse/id_registry.json`.

### 🔍 Check 2: Tính Độc nhất Khóa chính Toàn cục (Global Primary Key Uniqueness)
- Kiểm tra trùng lặp ID giữa 5 dự án: Không được phép có bất kỳ trùng lặp khóa chính nào (`unit_key`, `zone_key`, `channel_key`, `infra_key`, `funnel_event_id`, `price_event_id`, `diagnostic_id`).

### 🔍 Check 3: Ràng buộc Khóa ngoại (Cross-Table Foreign Key Integrity)
- Tất cả `unit_key` trong `fact_unit_inventory_snapshot`, `fact_sales_funnel_daily`, `fact_unit_price_history`, `dm_unit_friction_diagnostics` phải tồn tại trong `dim_unit_master`.
- Tất cả `zone_key` trong các bảng fact phải tồn tại trong `dim_zone_master`.
- Tất cả `project_key` trỏ đúng về `dim_project_profile`.

### 🔍 Check 4: Hợp đồng Logic Kinh doanh (Business Funnel & Price Contract)
- **Funnel**: `booking_reservations >= booking_cancellations` trên mọi dòng event.
- **Giá**: `net_price_vnd <= asking_price_vnd` trong `fact_unit_inventory_snapshot`.

---

## 4. Hướng dẫn Kỹ thuật Triển khai Code Python

### 📁 Cấu trúc Output Thư mục sau khi Gom

```text
warehouse/
├── dataset/                        <-- Central Master Dataset
│   ├── snapshot_manifest.csv       (1 dòng shared)
│   ├── semantic_config.csv         (47 dòng shared)
│   ├── dim_date.csv                (401 dòng shared)
│   ├── dim_project_profile.csv     (5 dòng master)
│   ├── dim_zone_master.csv         (89 dòng master)
│   ├── dim_unit_master.csv         (47.713 dòng master)
│   ├── dim_sales_channel.csv       (27 dòng master)
│   ├── dim_infrastructure_assets.csv (18 dòng master)
│   ├── dim_secondary_market_comps.csv (1.556 dòng master)
│   ├── fact_unit_inventory_snapshot.csv (340.286 dòng master)
│   ├── fact_sales_funnel_daily.csv (89.136 dòng master)
│   ├── fact_unit_price_history.csv (4.347 dòng master)
│   ├── fact_market_macro_monthly.csv (93 dòng master)
│   ├── fact_sales_channel_performance.csv (202 dòng master)
│   ├── dm_unit_friction_diagnostics.csv (4.882 dòng master)
│   ├── unit_diagnostic_causes.csv  (12.665 dòng master)
│   └── dataset_manifest.json       <-- Hash SHA256 & Row count metadata
```

### 💻 Lệnh Thực thi Đề xuất

```powershell
# Step 1: Kiểm tra Pre-merge Sanity toàn bộ 5 project packs
python warehouse/verify_warehouse.py

# Step 2: Chạy script gom 5 pack thành Master Dataset 16 bảng
python warehouse/assemble_dataset.py

# Step 3: Kiểm tra Quality Gate trên Master Dataset tập trung
python warehouse/verify_warehouse.py --target warehouse/dataset
```

---

## 5. Kế hoạch Bàn giao (Handover Matrix)

| Công đoạn | Phụ trách | Đầu ra | Trạng thái |
|---|---|---|:---:|
| 1. Integrate 5 Project Packs -> `DATA` | **Nguyễn Tuấn Anh** | 5 project folders (`project_100`–`500`) | **ĐÃ HOÀN THÀNH** |
| 2. `assemble_dataset` + `premerge_validate` | **Nguyễn Tuấn Anh** | Master Dataset tại `warehouse/dataset/` | **ĐANG THỰC HIỆN** |
| 3. Engine trung tâm -> Mart + Bridge | Lưu Xuân Dũng | Dimensional Mart & Bridge tables (Attribution = 1.000) | Chờ M3/N2 |
| 4. Data Quality Gates 100% | Hà Duy Anh | 6 nhóm DQ Gates Validation | Chờ M4 |
| 5. Data Dictionary & Release Manifest | Nguyễn Mai Huy | Tài liệu bàn giao & Manifest | Chờ M4 |
