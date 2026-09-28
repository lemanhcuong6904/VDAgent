# BÁO CÁO BỘ DỮ LIỆU DATA WAREHOUSE — VINHOMES GRAND PARK (VGP)

Báo cáo này tổng hợp lại toàn bộ bộ dữ liệu mock trong `mock_data/` (sinh từ
[`generate_vgp_mock.py`](generate_vgp_mock.py) + [`build_benchmark.py`](build_benchmark.py),
`seed=42`, cập nhật lần gần nhất 2026-09-29). Giải thích chi tiết logic từng bảng đã có
ở [`README.md`](README.md) — báo cáo này tập trung vào 3 câu hỏi: **có bao nhiêu dữ
liệu**, **dữ liệu nào thật/dữ liệu nào mock**, và **đã phủ được những kịch bản nào**.

---

## 1. Tổng số lượng dữ liệu

### 1.1. Toàn bộ data warehouse

| Chỉ số | Giá trị |
|---|---|
| Số bảng theo schema gốc (`data-warehouse-schema-v3.docx`) | 15/15 |
| Tổng số dòng dữ liệu (15 bảng schema, không tính file benchmark) | **43.433 dòng** |
| Tổng số dòng kể cả bộ câu hỏi benchmark (`16_benchmark_gold_sql.csv`) | 43.457 dòng |
| Tổng số ô dữ liệu (cells = Σ dòng × cột) | 570.755 ô |
| Tổng dung lượng 16 file CSV | ~2,96 MB |
| Số phân khu (project) | 6 |
| Số tòa/cụm (zone) | 68 (scale theo đúng số tòa thật cho Rainbow/Origami/Beverly) |
| Số căn hộ (unit) | **1.960** (~4,5% quy mô thật ~44.000+ căn — scale-up từ 725 căn theo yêu cầu) |
| Số kỳ snapshot chốt sổ | 6 (2026-04-30 → 2026-09-29) |

### 1.2. Chi tiết theo từng bảng

| # | Bảng | Số dòng | Số cột | Tầng dữ liệu |
|---|---|---:|---:|---|
| 1 | `snapshot_manifest` | 6 | 10 | Meta |
| 2 | `semantic_config` | 11 | 6 | Meta |
| 3 | `dim_date` | 730 | 8 | Dimension |
| 4 | `dim_project_profile` | 6 | 20 | Dimension |
| 5 | `dim_zone_master` | 68 | 11 | Dimension |
| 6 | `dim_unit_master` | 1.960 | 24 | Dimension |
| 7 | `dim_sales_channel` | 5 | 5 | Dimension |
| 8 | `dim_infrastructure_assets` | 4 | 8 | Dimension |
| 9 | `fact_unit_inventory_snapshot` | 11.611 | 22 | Fact (hạt nhân) |
| 10 | `fact_sales_funnel_daily` | 28.487 | 9 | Fact |
| 11 | `fact_unit_price_history` | 67 | 7 | Fact |
| 12 | `dim_secondary_market_comps` | 210 | 8 | Fact/Dim |
| 13 | `fact_market_macro_monthly` | 21 | 9 | Fact |
| 14 | `fact_sales_channel_performance` | 180 | 8 | Fact |
| 15 | `dm_unit_friction_diagnostics` | 67 | 15 | Serving Mart |
| — | `benchmark_gold_sql.csv` (phụ trợ, không thuộc schema gốc) | 24 | 9 | — |

**Nhận xét quy mô:** 2 bảng chiếm ~92% tổng số dòng là `fact_sales_funnel_daily`
(28.487 dòng, 66%) và `fact_unit_inventory_snapshot` (11.611 dòng, 27%) — đúng bản
chất 2 bảng có grain mịn nhất (căn × ngày tương tác / căn × kỳ snapshot). Số dòng
này **chỉ đại diện cho 1.960/~44.000+ căn thật của VGP** (~4,5% — đã scale từ 725
căn/~1,6% theo yêu cầu) — xem giới hạn ở `README.md` mục 5.

---

## 2. Nguồn dữ liệu: trường nào CÀO THẬT, trường nào MOCK

Chú thích: 🟢 = cào/xác thực từ nguồn thật (WebSearch, truy cập 2026-09-29) · 🟡 = mock
nhưng có căn cứ/kẹp trong khoảng thật · 🔴 = mock hoàn toàn, không có nguồn đối chiếu.
Danh sách nguồn URL đầy đủ ở `README.md` mục 2.

### 2.1. `snapshot_manifest`, `semantic_config`
🔴 **100% mock** — bảng meta/cấu hình nội bộ hệ thống, không tồn tại ở nguồn public.
`semantic_config` mã hóa lại các ngưỡng nghiệp vụ nêu ở mục 4 tài liệu gốc (VD
`overdue_threshold_days=90`); riêng `defect_unit_share_assumption` (18%) là hằng số
tự hiệu chỉnh vì văn bản gốc có số liệu nằm trong ảnh không đọc được.

### 2.2. `dim_date`
🔴 **100% sinh thuật toán** (lịch Gregorian 2025-01-01 → 2026-12-31) — không cần và
không có khái niệm "cào" cho bảng này.

### 2.3. `dim_project_profile` (6 phân khu)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| `project_name` | 🟢 reb.vn, vinhomes.vn, market.vinhomes.vn | Tên 6 phân khu xác thực thật |
| `province_city`, `district` | 🟢 kiến thức phổ thông đã xác thực | TP.HCM / TP. Thủ Đức |
| `developer_name`, `developer_tier`, `developer_origin` | 🟢 kiến thức phổ thông đã xác thực | Vingroup, Tier 1, Domestic |
| `construction_status` (Opus One = SUPERSTRUCTURE) | 🟢 market.vinhomes.vn, canho.com.vn | Đang mở bán 2026 là thật |
| `construction_status` (5 phân khu còn lại = HANDED_OVER) | 🟡 suy luận hợp lý | Không có ngày bàn giao chính xác công bố |
| `segment` | 🟡 suy từ tên dòng sản phẩm marketing (Sapphire/Ruby/Diamond) | KHÔNG phải phân loại chính thức CBRE/Savills/DKRA |
| `partner_bank_name` (Techcombank) | 🟡 có quan hệ đối tác thật với Vinhomes | Gán cứng cho từng phân khu là suy diễn |
| `primary_infra_id` (Metro số 1) | 🟡 VGP gần Metro số 1 là thật | Gán 1 infra cố định là đơn giản hóa |
| `expected_handover_date` | 🟡 suy theo thứ tự mở bán thật | Không phải ngày chính xác đã công bố |
| `market_id`, `market_name`, `project_id` | 🔴 tự đặt mã | Định danh nội bộ |
| `construction_progress_pct`, `distance_to_primary_infra_m` | 🔴 mock hoàn toàn | Số cụ thể tự đặt |
| `is_sales_permit_issued` | 🔴 mock (gán TRUE toàn bộ) | Không tìm được danh mục xác nhận từ Sở Xây dựng TP.HCM |
| `is_bank_guarantee_issued` | 🔴 mock (TRUE, riêng Manhattan = FALSE) | Manhattan = **kịch bản benchmark cấy tay**, xem mục 3.1 |
| `max_foreign_quota_exceeded` | 🔴 mock (FALSE toàn bộ) | Không có dữ liệu thật để đối chiếu |

### 2.4. `dim_zone_master` (68 tòa/cụm)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| Số lượng tòa của Rainbow (17), Origami (21), Beverly (6) | 🟢 reb.vn, vinhomes.vn | Dùng ĐÚNG số tòa thật để sinh đủ số dòng (không còn lấy mẫu 3 tòa như bản trước) |
| Số lượng cụm của Glory Heights/Manhattan/Opus One (8 mỗi phân khu) | 🔴 ước lượng | Không xác minh được số cụm/tòa thật cho 3 phân khu này |
| `zone_type` (Manhattan = LOW_RISE_VILLA) | 🟢 reb.vn | ~550 sản phẩm thấp tầng là thật |
| `handover_standard` | 🟡 kiến thức phổ thông thị trường Vinhomes | Không phải số liệu công bố riêng cho VGP |
| `zone_name`, `total_floors`, `basement_floors`, `units_per_floor`, `passenger_elevators`, `elevator_ratio` | 🔴 mock hoàn toàn | Tên tòa đại diện theo số thứ tự, số liệu ước lượng trong khoảng hợp lý |

### 2.5. `dim_unit_master` (1.960 căn)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| `net_area_m2` | 🟡 hiệu chỉnh theo giá thật đã cào | VD studio Origami ~29m² suy từ giá 1,75-1,85 tỷ ÷ ~61tr/m² |
| Toàn bộ các trường còn lại (`unit_type`, `bedroom_count`, `floor_number`, `balcony_orientation`, `view_primary_type`, `distance_to_trash_room_m`, `is_adjacent_elevator`, `dark_bedroom_count`, `west_facing_exposure_pct`, `taboo_view_type`...) | 🔴 mock hoàn toàn | Không có nguồn public nào cung cấp mặt bằng/thuộc tính chi tiết từng căn |

### 2.6. `dim_sales_channel` (5 đại lý)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| `channel_name`, `channel_tier` của Khải Hoàn Land, Đông Tây Land | 🟢 vinhomes.vn (danh sách đại lý chính thức) | Platinum / Platinum Plus là thật |
| Saigon Real (`channel_tier`) | 🟡 thuộc hệ Đất Xanh South (thật) nhưng cấp bậc chưa xác minh | |
| `active_brokers_count` (cả 5 đại lý) | 🔴 mock | Không public |
| INHOUSE-VINHOMES, AGENCY-GENERIC-01 | 🔴 mock (1 đại lý hoàn toàn hư cấu để đa dạng test) | |

### 2.7. `dim_infrastructure_assets` (4 công trình)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| `infra_name`, `infra_type`, `lifecycle_stage`, `original/revised_completion_year` | 🟢 tuoitre.vn, plo.vn, znews.vn, reb.vn | Cả 4 công trình (Metro số 1, Vành đai 3, Metro số 7, Cao tốc Long Thành) |
| `construction_progress_pct` (Vành đai 3 = 82.5) | 🟢 đúng số thật đã cào | |
| `construction_progress_pct` (Cao tốc Long Thành = 70.0) | 🔴 ước lượng riêng | Nguồn chỉ mô tả định tính ("đang thảm nhựa"), không có % chính xác |

### 2.8. `fact_unit_inventory_snapshot`, `fact_unit_price_history`
🔴 **100% mock** — dữ liệu CRM/vận hành nội bộ CĐT, không thể cào (đã đánh giá ở
lượt trả lời trước). Đơn giá được hiệu chỉnh theo băng giá thật đã cào theo từng
phân khu (🟡 gián tiếp qua `PROJECT_BAND`), nhưng từng dòng snapshot/sự kiện cụ thể
là kết quả mô phỏng.

### 2.9. `fact_sales_funnel_daily`, `fact_sales_channel_performance`
🔴 **100% mock** — hành vi khách hàng và hiệu suất sàn hoàn toàn nội bộ CRM, không
có nguồn public thay thế. `fact_sales_channel_performance` được tổng hợp
(aggregate) nhất quán từ chính `fact_unit_inventory_snapshot` đã sinh, không phải
random độc lập.

### 2.10. `dim_secondary_market_comps` (210 bản ghi)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| Khoảng giá The Rainbow (42-55tr/m²), Glory Heights (53,2-77,7tr/m²) | 🟢 batdongsan.com.vn | Đúng khoảng thật đã cào |
| Khoảng giá 4 phân khu còn lại (Origami, Beverly, Manhattan, Opus One) | 🔴 mock hoàn toàn | Đặc biệt Opus One thực tế CHƯA có giao dịch thứ cấp (dự án mới, chưa bàn giao) |
| Từng bản ghi cụ thể (`comp_id`, ngày, hướng ban công, `pink_book_status`) | 🟡 random nhưng kẹp trong khoảng giá thật (với Rainbow/Glory Heights) | |

### 2.11. `fact_market_macro_monthly` (21 tháng)

| Trường | Nguồn | Ghi chú |
|---|---|---|
| `floating_mortgage_rate_pct` (bình quân 10,5%/năm) | 🟢 techcombank.com, bidv.com.vn, vietnamnet.vn | Khảo sát 5 ngân hàng |
| `median_household_income_vnd` (330 triệu/năm) | 🟢 tuoitre.vn (nguồn thứ cấp Q&Me) | TP.HCM, cần đối chiếu thêm nếu dùng thật |
| `months_of_inventory_moi`, `absorption_rate_pct`, `macro_price_to_income_ratio` | 🔴 mock (công thức tương quan nghịch với lãi suất, tự dựng) | Không có báo cáo CBRE/Savills/VARS công khai đủ chi tiết cho riêng khu vực Thủ Đức |

### 2.12. `dm_unit_friction_diagnostics` (67 dòng)
🔴 **Derived 100%** từ các bảng mock ở trên, áp đúng công thức + thứ tự ưu tiên ma
trận 8 nguyên nhân (mục 4.3 tài liệu gốc) và Peer Group 6 tiêu chí (mục 4.1). Không
phải dữ liệu "cào" hay "mock ngẫu nhiên" độc lập — là kết quả tính toán lại.

### 2.13. Tổng hợp mức độ phủ nguồn thật theo bảng

| Bảng | % trường có ít nhất 1 phần 🟢/🟡 (không tính khóa/ID kỹ thuật) |
|---|---|
| `dim_project_profile` | ~50% (9/20 trường) |
| `dim_infrastructure_assets` | ~88% (7/8 trường) |
| `fact_market_macro_monthly` | ~22% (2/9 trường) |
| `dim_zone_master` | ~27% (3/11 trường) |
| `dim_secondary_market_comps` | ~25% (2/8 trường, ở mức "khoảng giá") |
| `dim_sales_channel` | ~40% (2/5 trường) |
| `dim_unit_master` | ~4% (1/24 trường) |
| Còn lại (meta, fact vận hành nội bộ, mart) | 0% — không có nguồn public khả dụng |

---

## 3. Scenario Coverage cho dự án

### 3.1. Ma trận 8 nguyên nhân cốt lõi (mục 4.3 tài liệu gốc)

| Mã nguyên nhân | Số căn trong `dm_unit_friction_diagnostics` | Nguồn gốc | Ghi chú |
|---|---:|---|---|
| `EXTREME_THERMAL_EXPOSURE` | 19 | Tự nhiên (mô phỏng) | Hướng Tây + thiếu chính sách hỗ trợ |
| `LOW_SALES_INCENTIVE` | 7 | Tự nhiên (mô phỏng) | Hoa hồng ≤1,5%, không thưởng nóng |
| `DEEP_FUNNEL_DROP_OFF` | 5 | Tự nhiên (mô phỏng) | Tỷ lệ rút cọc cao bất thường |
| `SEVERE_PHYSICAL_DEFECT` | 5 | 1 căn cấy tay + phần còn lại tự nhiên (quy mô lớn hơn nên tự trúng thêm) | Ép `distance_to_trash_room_m<3m` + kề thang máy |
| `LUMP_SUM_TICKET_BARRIER` | 4 | 1 căn cấy tay + phần còn lại tự nhiên | Ép diện tích lớn (118m²), giữ đơn giá/m² hợp lý |
| `SECONDARY_ARBITRAGE` | 3 | 1 căn cấy tay + phần còn lại tự nhiên | Ép đơn giá sơ cấp = 1,25× giá thứ cấp ước tính |
| `OVERPRICED_VS_PEER` | 3 | 1 căn cấy tay + phần còn lại tự nhiên | Ép đơn giá = 1,15× bình quân dự án, không lỗi |
| `LEGAL_PERMIT_BARRIER` | 2 | **100% cấy tay** | Manhattan `is_bank_guarantee_issued=FALSE`, chỉ 2 căn bị ép AVAILABLE |
| `MULTI_FACTOR_UNCLASSIFIED` (mã tự thêm, ngoài schema gốc) | 19 | Tự nhiên (fallback) | Căn quá hạn nhưng không khớp rõ điều kiện nào — cần rà soát thủ công |
| **Tổng** | **67** | 3 mã hoàn toàn tự nhiên, 4 mã có ≥1 ca tự nhiên bổ sung nhờ scale-up, 1 mã (`LEGAL_PERMIT_BARRIER`) vẫn 100% cấy tay | **8/8 mã gốc đã có ví dụ**; scale từ 725→1.960 căn giúp 4/5 mã trước đây chỉ có đúng 1 ca cấy tay nay đã có thêm ca tự nhiên trùng điều kiện, riêng `LEGAL_PERMIT_BARRIER` vẫn phụ thuộc hoàn toàn vào cấy tay vì phụ thuộc cờ pháp lý cấp dự án (chỉ 1 phân khu bị đặt FALSE) |

### 3.2. Độ đa dạng giá trị enum theo trường trọng yếu

| Trường | Giá trị đã xuất hiện | Giá trị CÒN THIẾU so với schema gốc |
|---|---|---|
| `inventory_status` | AVAILABLE, BOOKED, SOLD | ✅ Đủ 3/3 |
| `unit_type` | STUDIO,1PN,2PN,3PN,4PN,PENTHOUSE,DUPLEX | ✅ Đủ 7/7 |
| `taboo_view_type` | NONE, CEMETERY, WASTE_STATION, TEMPLE | ✅ Đủ 4/4 |
| `channel_tier` | TIER_1_EXCLUSIVE, TIER_2_GENERAL, INHOUSE | ✅ Đủ 3/3 |
| `lifecycle_stage` (infra) | PLANNING_APPROVED, UNDER_CONSTRUCTION, COMMERCIAL_OPERATION | ✅ Đủ 3/3 |
| `cancellation_reason` | PRICE_TOO_HIGH, DEFECT_FOUND, LOAN_REJECTED | ✅ Đủ 3/3 |
| `pink_book_status` | PINK_BOOK_AVAILABLE, SPA_ASSIGNMENT | ✅ Đủ 2/2 |
| `construction_status` | HANDED_OVER, SUPERSTRUCTURE | ❌ Thiếu FOUNDATION, TOPPED_OUT |
| `segment` | MID, MID_HIGH | ❌ Thiếu AFFORDABLE, LUXURY |
| `zone_type` | HIGH_RISE_TOWER, LOW_RISE_VILLA | ❌ Thiếu SHOPHOUSE |
| `handover_standard` | BASIC_FINISH, BARE_SHELL | ❌ Thiếu FULLY_FURNISHED |
| `change_reason` (price history) | STIMULATE_SLOW_MOVING | ❌ Thiếu MARKET_RALLY, CAMPAIGN (chưa mô phỏng ca tăng giá) |
| `developer_tier` | TIER_1 | ❌ Thiếu TIER_2, TIER_3 (chỉ 1 CĐT duy nhất trong toàn bộ dataset) |
| `developer_origin` | DOMESTIC | ❌ Thiếu FOREIGN_FDI (không có ý nghĩa với VGP thật vì Vingroup là CĐT duy nhất) |
| `max_foreign_quota_exceeded` | FALSE | ❌ Không có case TRUE (chưa test ràng buộc trần 30% khách nước ngoài) |

### 3.3. Coverage của bộ câu hỏi-SQL chuẩn (`16_benchmark_gold_sql.csv`)

| Tiêu chí | Kết quả |
|---|---|
| Tổng số câu hỏi | 24 |
| Độ khó EASY (1 bảng) | 5 câu |
| Độ khó MEDIUM (JOIN 2 bảng) | 8 câu |
| Độ khó HARD (JOIN ≥2 bảng / aggregation / window function) | 11 câu |
| Số bảng trong schema gốc được ít nhất 1 câu hỏi sử dụng | **15/15 (100%)** |
| Câu hỏi test trực tiếp ma trận 8 nguyên nhân | #9, #10, #11, #23 (4 câu) |
| Câu hỏi dùng window function (LAG) | #14 |
| Câu hỏi dùng aggregation nhiều tầng (GROUP BY + JOIN 2-3 bảng) | #8, #13, #15, #19 |
| Trạng thái chạy thật bằng DuckDB | 24/24 OK, có kết quả thật kèm theo |

### 3.4. Khoảng trống scenario còn lại (chưa phủ)

1. **Không có ca `LEGAL_PERMIT_BARRIER` "tự nhiên"** — toàn bộ đều là cấy tay ở 1
   phân khu duy nhất (Manhattan); chưa test được tình huống 1 phân khu vừa thiếu
   pháp lý vừa có nhiều nguyên nhân phụ khác cùng lúc.
2. **Không có phân khúc AFFORDABLE/LUXURY** và **không có CĐT Tier 2/3 hay FDI** —
   vì toàn bộ dataset chỉ có 1 CĐT (Vingroup) — hợp lý với thực tế VGP nhưng có
   nghĩa là các câu hỏi so sánh liên-CĐT/liên-phân khúc sẽ luôn trả về tập giá trị
   hẹp.
3. **Không có ca tăng giá** (`change_reason` = MARKET_RALLY/CAMPAIGN) trong
   `fact_unit_price_history` — script hiện chỉ mô phỏng chiều giảm giá để kích cầu.
4. **Không có `max_foreign_quota_exceeded = TRUE`** — chưa test được ràng buộc trần
   30% khách nước ngoài/tòa theo Luật KD BĐS 2023.
5. **Không có giá trị NULL có chủ đích** ở các trường optional quan trọng
   (`primary_infra_id`, `taboo_view_type`, `door_orientation`...) ngoài phân bố
   ngẫu nhiên tự nhiên — chưa có bộ câu hỏi test riêng hành vi NULL-handling của
   Agent.
6. **`FOUNDATION`, `TOPPED_OUT`** (construction_status) và **`SHOPHOUSE`**
   (zone_type) chưa xuất hiện — vì cả 6 phân khu mock đều đã ở 1 trong 2 trạng
   thái cực (đã bàn giao hoặc đang xây phần thân), chưa có phân khu ở giai đoạn
   móng/đã cất nóc.

**Kết luận:** bộ dữ liệu đã đạt coverage đầy đủ ở cấp **loại nguyên nhân chẩn đoán
(8/8)** và **cấp bảng (15/15 bảng có câu hỏi test)**, nhưng coverage ở cấp **giá trị
enum chi tiết** vẫn còn 7 giá trị thiếu (mục 3.2) — chủ yếu vì dataset chỉ mô hình
hoá đúng 1 CĐT/1 dự án thật với đặc điểm cố định. Muốn phủ nốt các khoảng trống này,
cần bổ sung thủ công tương tự cách đã làm ở mục 3.1 (cấy thêm 1-2 phân khu/căn có
thuộc tính biên), không thể có được từ mô phỏng ngẫu nhiên hay từ việc cào thêm dữ
liệu thật (vì VGP thật không có CĐT thứ hai hay phân khúc AFFORDABLE/LUXURY).
