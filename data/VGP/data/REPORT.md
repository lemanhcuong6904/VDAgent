# BÁO CÁO BỘ DỮ LIỆU DATA WAREHOUSE — VINHOMES GRAND PARK (VGP)

Bản quy mô THẬT (2026-09-30). Sau khi thử scale lên 300.000 căn (~6,8× thực tế) và
xác nhận không phù hợp, đã nghiên cứu bổ sung để lấy số liệu thật/ước lượng có
nguồn cho tất cả 6 phân khu, build lại đúng theo tổng đó (~33.619 căn), rồi audit
lại theo hợp đồng khóa Central DWH (`../warehouse/id_registry.json`) và sửa các vi
phạm cấu trúc phát hiện được. Giải thích chi tiết logic từng bảng ở
[`README.md`](README.md); báo cáo này trả lời 4 câu hỏi: **có bao nhiêu dữ liệu**,
**dữ liệu nào thật/mock**, **đã phủ được kịch bản nào**, và **có tuân thủ hợp đồng
khóa trung tâm không**.

---

## 1. Tổng số lượng dữ liệu

### 1.1. Toàn bộ data warehouse

| Chỉ số | Giá trị |
|---|---|
| Số bảng theo schema gốc | 15/15 |
| Số bảng mở rộng (Bridge + Attribution) | 2 |
| Tổng số dòng (17 bảng, không tính benchmark) | **354.706 dòng** |
| Tổng dung lượng | **~39,8 MB** |
| Số dự án (`project_key`) / phân khu / tòa-cụm / căn hộ | **1** / 6 / 61 / **33.619** (mục 1.2 — gộp `project_key` 6→1 theo hợp đồng khóa trung tâm) |
| Dải `unit_key` | **300.001 → 333.619** (trong dải 300001-399999 dành cho VGP theo `id_registry.json`) |
| `unit_code` | `VGP-U00001` → `VGP-U33619` (số tt toàn cục zero-pad 5 chữ số; `unit_id` cũ đã BỊ BỎ — mục 1.2) |
| Số kỳ snapshot | 6 (2026-04-30 → 2026-09-29) |
| **Kỳ active (báo cáo chính thức)** | **2026-06-30** (khác kỳ mới nạp gần nhất 2026-09-29 — mục 1.3) |
| dbt models + tests | 19 models (17 view + 2 table), 49 tests — **68/68 PASS** |
| Bộ câu hỏi-SQL chuẩn | 32 câu (28 gốc + 3 dùng dbt mart + 1 về active snapshot) — **32/32 OK** |

**Về offset `unit_key`**: cộng offset +300.000 để dành dải ID 1-299.999 cho một
nguồn dữ liệu khác trong Central DWH, tránh trùng khi gộp chung — chỉ đổi ID,
KHÔNG đổi số lượng bản ghi (vẫn 33.619 căn, không phải 300.000 dòng). Đã verify:
FK tham chiếu `unit_key` ở mọi bảng (fact, bridge, attribution, mart) khớp 100%.

### 1.2. Hợp đồng khóa Central DWH (`../warehouse/id_registry.json`)

VGP là 1/5 Project Data Pack hợp nhất vào Central DWH (`vdagent_dw_re`), task
**N3**. Audit lại theo hợp đồng phát hiện **6 vi phạm cấu trúc**, đã sửa hết:

| Khóa | Dải bắt buộc | Trước | Sau |
|---|---|---|---|
| `project_key` | 1 dòng duy nhất = 300 | 6 dòng (SAI kiến trúc) | ✅ 1 dòng `project_id="PRJ-VGP"` |
| `zone_key` | 301-399 | 1-61 | ✅ 301-361 |
| `channel_key` | 3001-3099 | 1-5 | ✅ 3001-3005 |
| `infra_key` | 3101-3199 | 1-4 | ✅ 3101-3104 |
| `unit_code` | `VGP-U`+5 số tt toàn cục | `01-00001` (sai format) | ✅ `VGP-U00001`.. |
| `dataset_id`/`version`/`source_system` | `vdagent_dw_re`/`3.1.0`/`ENTERPRISE_DW_RE` | `..._vgp`/`2.0.0`/`..._MOCK` | ✅ đúng cả 3 |

Quy tắc *"1 dự án = 1 project_key, phase con nằm dưới bằng zone_key"* buộc 6 phân
khu không còn là project riêng — các thuộc tính đặc thù (`segment`,
`construction_status`, `is_sales_permit_issued`, `is_bank_guarantee_issued`,
`expected_handover_date`) **chuyển xuống `dim_zone_master`** (8 cột mới).
`unit_id` cũ (prefix `VGP-U-` từ `unit_key`) đã **BỊ BỎ** — không phải field trong
hợp đồng (chỉ có `unit_code`). Chi tiết đầy đủ + bảng đối chiếu ở
[`README.md` mục 1.1](README.md).

Một bug thật phát sinh trong lúc sửa (không nằm trong 6 vi phạm trên, phát hiện
khi regenerate): công thức "đổi sàn phân phối" trong Bridge table giả định
`channel_key` liên tiếp 1..5 — vỡ khi re-key sang 3001-3005 (sinh giá trị ngoài
dải, vô hiệu FK). Đã sửa bằng ánh xạ qua vị trí trong mảng thay vì toán trực tiếp
trên giá trị `channel_key` (chi tiết mục 3.5).

### 1.3. Kỳ "active" — 2026-06-30 (mở rộng ngoài schema gốc)

Có căn cứ tường minh (không dùng quy ước ngầm) để phân biệt "kỳ active" (dùng để
báo cáo) và "kỳ mới nạp gần nhất":

| | Giá trị | Cơ chế xác định |
|---|---|---|
| Kỳ active | 2026-06-30 | Cột `snapshot_manifest.is_active` (BOOLEAN) + `semantic_config.active_snapshot_date_key` |
| Kỳ mới nạp gần nhất | 2026-09-29 | `MAX(snapshot_date)` — 3 kỳ sau active (07-31, 08-31, 09-29) coi là sơ bộ/chưa chính thức |

Đồng bộ qua 3 tầng để không có hardcode rải rác:
- **Python**: hằng số `ACTIVE_SNAPSHOT_DATE` trong `generate_vgp_mock.py`, dùng
  cho cả `snapshot_manifest.is_active` và logic "secondary gần đây".
- **dbt**: model helper `int_active_snapshot` (nguồn duy nhất, `ref()` bởi
  `int_secondary_stats`); test `assert_exactly_one_active_snapshot`.
- **Benchmark**: 7 câu hỏi (#6-8, #15, #19, #22, #24) dùng subquery
  `WHERE is_active` thay vì hardcode ngày; câu #32 kiểm tra trực tiếp khái niệm
  active vs mới nạp.

### 1.4. Chi tiết theo từng bảng

| # | Bảng | Số dòng | Số cột | Dung lượng | Tầng |
|---|---|---:|---:|---:|---|
| 1 | `snapshot_manifest` | 6 | 11 (+`is_active`, mở rộng) | <0,01 MB | Meta |
| 2 | `semantic_config` | 12 | 6 | <0,01 MB | Meta |
| 3 | `dim_date` | 730 | 8 | 0,03 MB | Dimension |
| 4 | `dim_project_profile` | **1** (gộp từ 6, `project_key=300`) | 20 | <0,01 MB | Dimension |
| 5 | `dim_zone_master` | 61 | **19** (+8 cột mở rộng thuộc tính phân khu) | 0,01 MB | Dimension |
| 6 | `dim_unit_master` | 33.619 | **23** (-1: bỏ `unit_id`) | 3,86 MB | Dimension |
| 7 | `dim_sales_channel` | 5 | 5 | <0,01 MB | Dimension |
| 8 | `dim_infrastructure_assets` | 4 | 8 | <0,01 MB | Dimension |
| 9 | `fact_unit_inventory_snapshot` | 200.545 | 22 | 28,67 MB | Fact (hạt nhân) |
| 10 | `fact_sales_funnel_daily` | 59.832 | 9 | 2,10 MB | Fact |
| 11 | `fact_unit_price_history` | 454 | 7 | 0,03 MB | Fact |
| 12 | `dim_secondary_market_comps` | 360 | **10** (+2: `sub_project_id`/`sub_project_name`) | 0,03 MB | Fact/Dim |
| 13 | `fact_market_macro_monthly` | 21 | 9 | <0,01 MB | Fact |
| 14 | `fact_sales_channel_performance` | **30** (giảm từ 180: `project_key` giờ hằng số) | 8 | 0,01 MB | Fact |
| 15 | `dm_unit_friction_diagnostics` | 2.144 | 15 | 0,56 MB | Serving Mart |
| 16 | `bridge_unit_channel_history` **(mở rộng)** | 36.975 | 7 | 1,51 MB | Bridge |
| 17 | `fact_funnel_attribution` **(mở rộng)** | 19.907 | 9 | 1,14 MB | Attribution |
| — | `18_benchmark_gold_sql.csv` (phụ trợ) | 32 | 9 | 0,02 MB | — |

**Quy mô theo phân khu** (số tòa thật / số căn dùng):

| Phân khu | Số tòa | Số căn | % tổng |
|---|---:|---:|---:|
| The Rainbow | 17 | 10.404 | 31% |
| The Origami | 21 | 11.991 | 36% |
| The Beverly | 6 | 5.088 | 15% |
| Glory Heights | 5 | 3.500 | 10% |
| The Manhattan (villa) | 8 cụm | 552 | 2% |
| The Opus One | 4 | 2.084 | 6% |
| **Tổng** | **61** | **33.619** | 100% |

---

## 2. Nguồn dữ liệu: CÀO THẬT vs MOCK

🟢 cào thật · 🟡 mock có căn cứ · 🔴 mock hoàn toàn. Nguồn URL đầy đủ ở README mục 3.

### 2.1. Cấu trúc zone/unit dùng số liệu thật

| Phân khu | Số tòa dùng | Số căn/tòa |
|---|---:|---|
| Rainbow | 17 tòa (🟢) | ~612 căn/tòa (🟡 chia đều theo tổng thật 10.404) |
| Origami | 21 tòa (🟢) | ~571 căn/tòa (🟢 khớp đúng tỷ lệ thật 12.000/21) |
| Beverly | 6 tòa (🟢) | 848 căn/tòa (🟡 tổng thật 5.088, chia đều) |
| Glory Heights | 5 tòa (🟢) | 700 căn/tòa (🟡 tổng ước lượng 3.500) |
| Manhattan | 8 cụm (🔴 ước lệ) | 69 căn/cụm (🟢 tổng thật 552 ≈ 550) |
| Opus One | 4 tòa (🟢: OS1-3,OS5) | Số căn THẬT từng tòa (🟢 578/480/448/578) |

`units_per_floor` **dẫn xuất** từ (số căn thật ÷ `total_floors`) thay vì random
độc lập — với Opus One, kết quả trùng khớp CHÍNH XÁC với công thức thật đã cào
(34 tầng×17 căn/tầng=578, 32×15=480, 32×14=448, 34×17=578).

### 2.2. Tổng hợp % trường có nguồn thật theo bảng

| Bảng | % trường có nguồn thật |
|---|---|
| `dim_infrastructure_assets` | ~88% |
| `dim_zone_master` | ~36% (nhờ số tòa + số căn/tòa Opus One đều có nguồn thật) |
| `dim_project_profile` | ~50% |
| `dim_sales_channel` | ~40% |
| `fact_market_macro_monthly` | ~22% |
| `dim_secondary_market_comps` | ~25% |
| `dim_unit_master` | ~4% |
| `bridge_unit_channel_history`, `fact_funnel_attribution` | 0% (bảng mở rộng, không có trong schema gốc) |
| Còn lại (meta, fact vận hành nội bộ, mart) | 0% |

---

## 3. Scenario Coverage

### 3.1. Ma trận 8 nguyên nhân cốt lõi

| Mã nguyên nhân | Số dòng (6 kỳ) | Nguồn gốc |
|---|---:|---|
| `MULTI_FACTOR_UNCLASSIFIED` (mã tự thêm, fallback) | 761 | Tự nhiên |
| `EXTREME_THERMAL_EXPOSURE` | 646 | Tự nhiên |
| `OVERPRICED_VS_PEER` | 178 | Tự nhiên |
| `LUMP_SUM_TICKET_BARRIER` | 160 | Tự nhiên |
| `SEVERE_PHYSICAL_DEFECT` | 158 | Tự nhiên |
| `LOW_SALES_INCENTIVE` | 133 | Tự nhiên |
| `DEEP_FUNNEL_DROP_OFF` | 92 | Tự nhiên |
| `LEGAL_PERMIT_BARRIER` | 12 | **100% cấy tay** |
| `SECONDARY_ARBITRAGE` | 4 | Tự nhiên (mỏng — chỉ 4 ca) |
| **Tổng** | **2.144** | **8/8 mã gốc có mặt, 7/8 mã tự nhiên** |

7/8 mã vẫn tự nổi lên tự nhiên (không cần cấy tay) ở quy mô 33,6k, dù
`SECONDARY_ARBITRAGE` khá mỏng vì xác suất đồng thời "giá sơ cấp cao hơn thứ cấp
≥15% + có giao dịch thứ cấp gần đây" thấp và quy mô Opus One (phân khu duy nhất
còn tồn kho) chỉ ~2.084 căn. `LEGAL_PERMIT_BARRIER` vẫn 100% cấy tay vì đây là cờ
**cấp phân khu** (`dim_zone_master.is_bank_guarantee_issued`) — không phụ thuộc
quy mô mẫu, chỉ phụ thuộc số phân khu bị gán `FALSE` (hiện 1/6, Manhattan).

### 3.2. Xác thực chéo Python ↔ SQL/dbt

Toàn bộ 2.144 dòng chẩn đoán được tính 2 lần độc lập (Python +
`dbt_vgp/models/marts/dm_unit_friction_diagnostics.sql`) — **khớp tuyệt đối 100%**
(test `assert_dbt_matches_python_diagnostics`, 0 dòng lệch), kể cả sau khi
`project_key` bị gộp 6→1 (logic peer-group/permit-bank chuyển sang dùng
`dim_zone_master.sub_project_id` ở cả 2 pipeline — mục 1.2).

### 3.3. dbt: Bridge + Attribution + mart consolidation

| Hạng mục | Trạng thái |
|---|---|
| Staging model Bridge/Attribution | `stg_bridge_unit_channel_history`, `stg_fact_funnel_attribution` — đủ cột, có test |
| Test ràng buộc nghiệp vụ | Đúng 1 dòng `is_current`/căn (Bridge); `attribution_weight` ∈ (0,1] và tổng trọng số theo (unit_key, outcome_date_key) ≈ 1,0 (Attribution) |
| Mart dùng Bridge+Attribution | `mart_channel_attribution_performance` — 1 dòng/kênh, tổng hợp số căn đang/đã giao, số touchpoint, tổng trọng số attribution, tỷ lệ chuyển đổi. Không nhân bản logic `dm_unit_friction_diagnostics` |
| `dbt build` | **68/68 PASS** (19 model, 49 test) |

Toàn bộ khóa trong Bridge (`unit_key`, `channel_key`) và Attribution
(`funnel_event_id`, `unit_key`, `channel_key`) verify tham chiếu đúng dữ liệu
nguồn qua test `relationships` — không có bản ghi mồ côi.

**Portability**: `_sources.yml`, `profiles.yml`, `generate_vgp_mock.py`,
`build_benchmark.py` dùng đường dẫn tương đối/tự suy từ vị trí file (không
hardcode tuyệt đối). Đã verify thật: copy toàn bộ project sang đường dẫn khác
hoàn toàn, chạy lại cả 3 bước — 68/68 dbt PASS, 32/32 benchmark OK.

### 3.4. Coverage bộ câu hỏi-SQL chuẩn (`18_benchmark_gold_sql.csv`)

| Tiêu chí | Kết quả |
|---|---|
| Tổng số câu hỏi | **32** (28 gốc + 3 câu dùng dbt mart #29-31 + 1 câu active snapshot #32; 5 EASY / 13 MEDIUM / 14 HARD) |
| Số bảng gốc (17) được ≥1 câu dùng | 17/17 (100%) |
| Câu hỏi test ma trận 8 nguyên nhân | #9, #10, #11, #23 |
| Câu hỏi dùng Bridge / Attribution (raw CSV) | #25-26 / #27-28 |
| Câu hỏi dùng mart consolidation (qua dbt artifact thật, ATTACH `vgp.duckdb`) | #29-31 |
| Câu hỏi test khái niệm active vs mới nạp (subquery động, không hardcode) | #6, #7, #8, #15, #19, #22, #24, **#32** |
| Câu hỏi đổi join sau khi gộp `project_key` (dùng `dim_zone_master`/`sub_project_*` thay `dim_project_profile`) | #1, #2, #6, #8, #11, #19, #21 |
| Trạng thái chạy thật (DuckDB) | **32/32 OK** |

Câu #29-31 đọc **trực tiếp** từ bảng `mart_channel_attribution_performance` đã
materialize trong `vgp.duckdb` (không tính lại bằng SQL độc lập) — kiểm chứng
đúng chính artifact dbt, không phải bản sao logic.

### 3.5. Audit log — bug đã phát hiện & sửa (theo thứ tự thời gian)

1. **`avg_days_to_sell` sai công thức**: `fact_sales_channel_performance.avg_days_to_sell`
   bị tính bằng `mean(unsold_days_dom)` (công thức DOM lũy kế
   `snapshot_date - release_date`, đúng cho `unsold_days_dom` theo docx) thay vì
   công thức riêng của chính nó ("số ngày bán trung bình" =
   `sold_date - release_date`). Vì SOLD chiếm 97,7% `fact_unit_inventory_snapshot`,
   giá trị bị thổi phồng tới ~2.130 ngày (~5,8 năm) trung bình, có dòng 3.003
   ngày. Đã sửa trong `generate_vgp_mock.py` — kết quả sau sửa: trung bình ~144
   ngày (54-181 ngày), hợp lý. Không ảnh hưởng `unsold_days_dom` gốc,
   `is_overdue_flag`, `dm_unit_friction_diagnostics` (chỉ dùng DOM cho căn
   AVAILABLE, nơi công thức docx vốn đã đúng).

2. **Zone biệt thự hardcode sai `total_floors`/`units_per_floor`**:
   `dim_zone_master.total_floors`/`units_per_floor` của 8 zone biệt thự (Manhattan
   Cum, `LOW_RISE_VILLA`) hardcode `4`/`1` trong khi mỗi zone thực có 69 căn —
   phá vỡ invariant "derive từ số căn thật" áp dụng cho zone HIGH_RISE_TOWER
   khác. Docx mô tả 2 trường này là khái niệm tòa apartment và để `total_floors`
   nullable, không có hướng dẫn tường minh cho villa (spec-gap, không phải lỗi
   cố ý). Đã sửa: ghi **NULL** cho 8 zone này (tách 1 hằng số nội bộ
   `total_floors_gen=4` chỉ dùng để sinh `floor_number` cấp căn, không ghi ra
   CSV). `dim_unit_master.floor_number` cấp căn giữ nguyên (docx bắt buộc không
   null). Verify: 552/552 `floor_number` biệt thự không null, 0 zone
   HIGH_RISE_TOWER bị NULL lây.

3. **`channel_key` re-key làm vỡ công thức đổi-sàn**: khi sửa theo hợp đồng khóa
   Central DWH (mục 1.2), công thức "đổi sàn phân phối" trong Bridge table
   `other_channel = ((channel_key - 1 + offset) % n_channel) + 1` giả định
   `channel_key` liên tiếp 1..5 — sau re-key sang 3001-3005, công thức sinh giá
   trị ngoài dải hợp lệ (vô hiệu FK `relationships`). Đã sửa bằng ánh xạ qua VỊ
   TRÍ trong mảng `channel_key` hợp lệ. Phát hiện qua `dbt build` báo FAIL
   `relationships` (3.356 + 921 dòng mồ côi) — sửa xong PASS lại 68/68.

**Đã kiểm tra và loại trừ (không phải lỗi)**: `dim_comps.project_id`/`sub_project_id`
join theo natural key (đúng thiết kế); `price_spread_vs_peer_pct` âm là bình
thường (căn định giá dưới trung vị peer — `OVERPRICED_VS_PEER` xác nhận tương
quan đúng với spread dương cao); số dòng `fact_unit_inventory_snapshot` "thiếu"
so với units×snapshots là do căn chưa tới `release_date` chưa xuất hiện ở kỳ sớm
(đúng thiết kế, không phải mất dữ liệu).

**Chưa xác minh được (thiếu đặc tả gốc)**: `SNAPSHOT_RULES.md` yêu cầu
`attribution_score` cộng = 1,000/chẩn đoán — từ khóa này không xuất hiện trong cả
3 bản docx cục bộ và tài liệu thẩm quyền thật (`data-warehouse-schema.md v3.1.0`)
không có trên máy. Không tự bịa cột mới; tạm coi đáp ứng về tinh thần qua
`fact_funnel_attribution.attribution_weight` (đã cộng ≈1,000/căn, test PASS) —
đây là suy đoán, không phải xác nhận chắc chắn (chi tiết README mục 8.5).

### 3.6. Giới hạn/khoảng trống còn lại (chưa giải quyết)

1. **Peer Group vẫn đơn giản hóa 2 tầng** (không đủ 6 tiêu chí gốc) — quyết định
   giữ nguyên, vì đơn giản hóa này giúp dễ đọc/bảo trì và không ảnh hưởng đáng kể
   tới kết quả ở quy mô này (đã verify khớp dbt).
2. **Số căn/tòa của 4/6 phân khu vẫn là chia đều** theo tổng phân khu (không có số
   liệu thật riêng từng tòa như Opus One).
3. `SECONDARY_ARBITRAGE` mỏng (4 ca) — nếu cần nhiều ví dụ hơn, vẫn cần cấy tay bổ
   sung tương tự cách làm với `LEGAL_PERMIT_BARRIER`.
4. Enum gaps không đổi (AFFORDABLE/LUXURY, FOUNDATION/TOPPED_OUT, SHOPHOUSE,
   FULLY_FURNISHED, MARKET_RALLY/CAMPAIGN, quota nước ngoài TRUE) — xem README.
5. `mart_channel_attribution_performance` tổng hợp toàn bộ lịch sử, chưa có chiều
   thời gian/kỳ (Bridge/Attribution gốc không có khái niệm "kỳ chốt sổ").
6. 8 staging model còn lại (`dim_date`, `snapshot_manifest`, `dim_infrastructure_assets`,
   `fact_unit_price_history`, `fact_sales_channel_performance`...) đã khai báo
   source nhưng chưa có file staging `.sql` riêng.
7. **2 config `semantic_config` còn `PENDING`** (`defect_unit_share_assumption`,
   `attribution_model_default`) — chưa được phê duyệt chính thức, không thuộc
   thẩm quyền tự duyệt. Chi tiết phạm vi ảnh hưởng ở README mục 8.5.
8. **`attribution_score` theo `SNAPSHOT_RULES.md`** chưa xác minh được do thiếu
   đặc tả gốc v3.1.0 — xem mục 3.5.
