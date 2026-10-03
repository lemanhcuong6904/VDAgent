# SNAPSHOT_RULES — VDAgent Central DWH (registry v3.1.1)

> Quy tắc bất biến áp dụng cho **cả 5 Project Data Packs**. Nguồn chuẩn:
> `vdagent-xdg/export/snapshot_manifest.csv` + `vdagent-xdg/seeds/semantic_config.json`.
> Hợp đồng khóa: `warehouse/id_registry.json`.

## 1. Snapshot bất biến

| Trường | Giá trị bắt buộc |
|---|---|
| `snapshot_id` | `SNAP-20260630-01` |
| `dataset_id` | `vdagent_dw_re` |
| `dataset_version` / `semantic_version` | `3.1.0` |
| `snapshot_date` | `2026-06-30` |
| `snapshot_date_key` | `20260630` |
| `timezone` | `Asia/Ho_Chi_Minh` |
| `currency` | `VND` |
| `price_basis` | `ASKING_EXCL_VAT_EXCL_MAINT` |
| `area_basis` | `NET_INTERNAL_M2` |
| `source_system` | `ENTERPRISE_DW_RE` |

Mọi phép tính DOM căn cứ đúng mốc `snapshot_date`.

## 2. Ràng buộc dữ liệu (áp dụng khi sinh/hiệu chỉnh pack)

- `net_price_vnd <= asking_price_vnd`.
- `AVAILABLE => sold_date IS NULL`; `SOLD => sold_date >= release_date`.
- `unsold_days_dom = snapshot_date - release_date`.
- `is_overdue_flag = TRUE` khi `AVAILABLE` và `unsold_days_dom > 90`.
- Chẩn đoán chỉ tồn tại khi `inventory_status='AVAILABLE'` và `unsold_days_dom > 90`.
- 8 mã nguyên nhân cốt lõi; `attribution_score` cộng = `1.000` / chẩn đoán.
- `fact_unit_inventory_snapshot` grain = 1 dòng / `unit_key` / `snapshot_date_key`.

## 3. Dải khóa 5 dự án (tóm tắt từ id_registry.json)

| project_key | project_id | prefix | unit_key | zone_key | channel_key | infra_key | Owner | Task |
|---|---|---|---|---|---|---|---|---|
| 100 | PRJ-VHOP | OCP-U | 100001-199999 | 101-199 | 1001-1099 | 1101-1199 | Lưu Xuân Dũng | N7 |
| 200 | PRJ-VHSC | SMC-U | 200001-299999 | 201-299 | 2001-2099 | 2101-2199 | Nguyễn Quang Huy | N4 |
| 300 | PRJ-VGP | VGP-U | 300001-399999 | 301-399 | 3001-3099 | 3101-3199 | Hà Duy Anh | N3 |
| 400 | PRJ-MAS-CP | MAS-U | 400001-499999 | 401-499 | 4001-4099 | 4101-4199 | Nguyễn Tuấn Anh | N6 |
| 500 | PRJ-RISK-PHU-MY-BRVT | TST-U | 500001-599999 | 501-599 | 5001-5099 | 5101-5199 | Nguyễn Mai Huy | N5 |

### 3.1. Khóa sự kiện và comparable khi hợp nhất pack

DDL dùng `funnel_event_id`, `price_event_id` và `comp_id` làm PK toàn bảng. Khi tạo pack canonical bằng `organize_pack.py` (pipeline đã retire 2026-10-04), giữ lại giá trị ID nguồn qua phép ánh xạ ổn định sau:

| Pack | Cột | ID canonical | ID nguồn có thể khôi phục |
|---|---|---|---|
| 100 — Ocean Park | `funnel_event_id`, `price_event_id` | `10_000_000_000 + ID nguồn` | Trừ `10_000_000_000` |
| 200 — Smart City | `funnel_event_id` | `20_000_000_000 + ID nguồn` | Trừ `20_000_000_000` |
| 100 — Ocean Park | `comp_id` | `OCP-` + ID nguồn | Bỏ tiền tố `OCP-` |

Các pack 300/400/500 giữ ID hiện có; riêng ID funnel của pack 300 còn được dùng trong attribution nguồn. Quality gate `verify_warehouse.py` từng kiểm PK/UK của cả 13 bảng project trên hợp của 5 pack trước bước assemble; pipeline đó đã retire (2026-10-04), các ánh xạ ID ở trên vẫn là quy tắc của dữ liệu trong kho chuẩn.

## 4. Bảng re-key Ocean Park (hiện -> đích) — cho N7

| Đối tượng | Hiện tại (đã ship ở DATA) | Đích |
|---|---|---|
| project row | `PRJ-VHOP` (project_key=1) + `PRJ-VHOP-BEVERLY` (project_key=2) | Gộp về `PRJ-VHOP`, `project_key=100` |
| The Beverly | zone_key=105 trỏ project_key=2 | zone_key=105 trỏ project_key=100 |
| zone_key khác | 101-104, 106-109 (project_key=1) | giữ zone_key, đổi project_key->100 |
| unit_code | `SAPPHIRE1-...` | `OCP-U00001+` |
| unit_key | (dải cũ) | `100001+` |
| channel_key | 201-204 | 1001-1004 |
| infra_key | 301-305 | 1101-1105 |

## 5. Thông báo team (khởi động N3-N7 ngay)

- Đọc `warehouse/id_registry.json` trước khi sinh dữ liệu; chỉ dùng dải của mình.
- Snapshot ép cứng `2026-06-30 / VND / NET_INTERNAL_M2` cho mọi pack.
- Grand Park & Risk đang để snapshot 09-29 -> phải ép về 06-30 (N3, N5).
- Risk đang là `project_key=202` (đè dải 200) -> đổi sang 500 trước khi merge (N5).
