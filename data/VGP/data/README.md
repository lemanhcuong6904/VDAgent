# Bộ dữ liệu mock — Vinhomes Grand Park (VGP)

Bộ dữ liệu mô phỏng **15 bảng gốc** trong `data-warehouse-schema-v3.docx` (VDAGENT,
Dimensional Star Schema) áp cho dự án thật **Vinhomes Grand Park**, TP. Thủ Đức,
TP.HCM — cộng thêm **2 bảng mở rộng** (Bridge + Attribution, ngoài schema gốc) và
**1 dbt project thật** (`../dbt_vgp/`) tái hiện logic chẩn đoán bằng SQL. Đồng thời
tuân thủ **hợp đồng khóa Central DWH** (`../warehouse/id_registry.json`) — VGP là
1 trong 5 Project Data Pack hợp nhất vào 1 kho dữ liệu trung tâm.

Sinh bằng [`generate_vgp_mock.py`](generate_vgp_mock.py) (`seed=42`, vector hóa
bằng pandas/numpy) + [`build_benchmark.py`](build_benchmark.py) (bộ câu hỏi-SQL
chuẩn, verify bằng DuckDB). Cập nhật lần gần nhất: 2026-09-30 — **bản quy mô THẬT**
(đã thử scale lên 300.000 căn ở bản trước rồi xác nhận KHÔNG phù hợp thực tế, quay
lại đúng quy mô thật của 6 phân khu; sau đó audit lại theo hợp đồng khóa Central
DWH và sửa các vi phạm cấu trúc — xem mục 1.1).

## 1. Phạm vi & quy mô

| Chỉ số | Giá trị |
|---|---|
| Số dự án (`project_key`) | **1** — `project_key=300`, `project_id="PRJ-VGP"` (xem mục 1.1) |
| Số phân khu (sub-project, ở cấp `dim_zone_master`) | 6 |
| Số tòa/cụm (zone) | **61** (đúng số tòa thật), `zone_key` dải **301-361** |
| **Số căn hộ (unit)** | **33.619** — tổng THẬT/ước lượng có nguồn của 6 phân khu này (xem mục 2) |
| **Dải `unit_key`** | **300.001 → 333.619** (trong dải 300001-399999 dành cho VGP) |
| **`unit_code`** | **`VGP-U00001` → `VGP-U33619`** (khóa nghiệp vụ, số thứ tự toàn cục zero-pad 5 chữ số) |
| Số kỳ snapshot chốt sổ | 6 (2026-04-30 → 2026-09-29) |
| **Kỳ active (báo cáo chính thức)** | **2026-06-30** — khác kỳ mới NẠP gần nhất (2026-09-29), xem mục 1.2 |
| `dm_unit_friction_diagnostics` | Tính cho **cả 6 kỳ** |
| Tổng số dòng toàn bộ 17 bảng | **354.706 dòng** (~39,8 MB) |

**Quan trọng — 33.619 KHÔNG phải và KHÔNG nên bị hiểu là "~44.000 căn của VGP"**:
con số 44.000 (hoặc 43.500) là tổng **TOÀN BỘ dự án VGP** (71 tòa, gồm cả các phân
khu khác chưa được mô hình hóa ở đây + shophouse + phần lớn townhouse/villa nằm
ngoài 6 phân khu này). Bộ dữ liệu này chỉ mô hình hóa đúng 6 phân khu đặt tên, nên
trần thực tế của NÓ là tổng thật của 6 phân khu đó (~33,6k), không phải trần của cả
VGP.

### 1.1. Hợp đồng khóa Central DWH (`../warehouse/id_registry.json`)

VGP là **1 trong 5 Project Data Pack** hợp nhất vào 1 Central Data Warehouse
(`vdagent_dw_re`) theo hợp đồng khóa `id_registry.json` + `SNAPSHOT_RULES.md`
(task **N3**, owner Hà Duy Anh). Audit lại theo hợp đồng này phát hiện **6 vi
phạm cấu trúc** so với bản trước, đã sửa hết:

| Khóa | Dải bắt buộc | Trước khi sửa | Sau khi sửa |
|---|---|---|---|
| `project_key` | **1 dòng duy nhất = 300** | 6 dòng (1/phân khu) — **SAI kiến trúc** | ✅ 1 dòng, `project_id="PRJ-VGP"` |
| `zone_key` | 301-399 | 1-61 | ✅ 301-361 |
| `unit_key` | 300001-399999 | 300001-333619 | ✅ không đổi (đã đúng từ trước) |
| `channel_key` | 3001-3099 | 1-5 | ✅ 3001-3005 |
| `infra_key` | 3101-3199 | 1-4 | ✅ 3101-3104 |
| `unit_code` | `VGP-U` + số tt toàn cục zero-pad 5 (vd `VGP-U00001`) | `01-00001` (số tt trong zone, sai format) | ✅ `VGP-U00001`..`VGP-U33619` |
| `dataset_id` | `vdagent_dw_re` | `vdagent_dw_re_vgp` | ✅ `vdagent_dw_re` |
| `dataset_version`/`semantic_version` | `3.1.0` | `2.0.0` | ✅ `3.1.0` |
| `source_system` | `ENTERPRISE_DW_RE` | `ENTERPRISE_DW_RE_MOCK` | ✅ `ENTERPRISE_DW_RE` |

**Gộp `project_key` 6→1 kéo theo thay đổi mô hình**: quy tắc *"1 dự án = 1
`project_key`, phase/tòa con nằm dưới bằng `zone_key`"* nghĩa là 6 phân khu
(Rainbow/Origami/Beverly/Glory Heights/Manhattan/Opus One) không còn là project
riêng — các thuộc tính đặc thù từng phân khu (`segment`, `construction_status`,
`is_sales_permit_issued`, `is_bank_guarantee_issued`, `expected_handover_date`)
**chuyển xuống `dim_zone_master`** (8 cột mới, mỗi zone kế thừa đúng 1 bộ giá trị
của phân khu nó thuộc về). `dim_project_profile` giờ chỉ còn 1 dòng mang giá trị
**tổng hợp/mô tả** (không dùng để suy luận chẩn đoán — logic chẩn đoán
`LEGAL_PERMIT_BARRIER` dùng giá trị đúng cấp zone). Tương tự,
`dim_secondary_market_comps.project_id` giờ là hằng số `"PRJ-VGP"` (khớp FK với
`dim_project_profile` 1 dòng); thêm 2 cột mới `sub_project_id`/`sub_project_name`
giữ phân biệt phân khu như trước.

`unit_id` (khóa mở rộng cũ, prefix `VGP-U-` từ `unit_key`) đã **BỊ BỎ** — không
phải field trong hợp đồng `id_registry.json` (chỉ có `unit_code`), giữ 2 field
gần-trùng-lặp không cần thiết sau khi `unit_code` đã chuẩn hóa đúng spec.
`unit_key` (surrogate, dùng JOIN) không đổi.

**Bug thật phát hiện khi sửa**: công thức "đổi sàn phân phối" (Bridge table)
`other_channel = ((channel_key - 1 + offset) % n_channel) + 1` giả định
`channel_key` là số nguyên liên tiếp 1..5 — sau khi re-key sang 3001-3005, công
thức này sinh ra `channel_key` NGOÀI dải hợp lệ (vô hiệu FK). Đã sửa: ánh xạ qua
VỊ TRÍ trong mảng `channel_key` hợp lệ thay vì làm toán trực tiếp trên giá trị.

### 1.2. Kỳ "active" (báo cáo chính thức) — 2026-06-30

Có **căn cứ tường minh** để phân biệt 2 khái niệm (không dùng quy ước ngầm "mới
nhất = MAX(snapshot_date)"):

| Khái niệm | Giá trị | Nguồn xác định |
|---|---|---|
| Kỳ **active** (chính thức dùng để báo cáo) | **2026-06-30** | Cột `snapshot_manifest.is_active` (BOOLEAN) + `semantic_config.active_snapshot_date_key=20260630` |
| Kỳ **mới NẠP gần nhất** | 2026-09-29 | `MAX(snapshot_date)` — dữ liệu đã nạp tới đây, nhưng 3 kỳ sau active (07-31, 08-31, 09-29) coi là **sơ bộ/chưa chính thức** |

`snapshot_manifest.is_active` và `semantic_config.active_snapshot_date_key` là
**2 cột/dòng MỞ RỘNG ngoài schema v3 gốc**. dbt có model helper
`int_active_snapshot` làm nguồn duy nhất cho khái niệm "active" (xem
`../dbt_vgp/README.md`) — mọi model/câu hỏi benchmark cần "kỳ hiện hành" đều tham
chiếu tới đây, không hardcode ngày rải rác.

## 2. Quy mô từng phân khu — nguồn & độ tin cậy

| Phân khu | Số tòa dùng | Số tòa THẬT | Số căn dùng | Nguồn & độ tin cậy |
|---|---:|---:|---:|---|
| The Rainbow | 17 | 🟢 17 (thật) | 10.404 | 🟡 ~10.343-10.435 (2 nguồn: vinhomes.vn, market.vinhomes.vn, không hoàn toàn khớp nhau — lấy trung bình) |
| The Origami | 21 | 🟢 21 (thật) | 11.991 | 🟢 12.000 (thật, xác nhận nhiều nguồn) |
| The Beverly | 6 | 🟢 6 (thật) | 5.088 | 🟡 5.088 là số cho **toàn cụm** (gồm cả The Beverly Solari) — không tách được riêng 6 tòa chính, dùng tạm cho cả 6 |
| Glory Heights | 5 | 🟢 5 (thật) | 3.500 | 🟡 nguồn không thống nhất (3.450-3.620), lấy giá trị giữa |
| The Manhattan | 8 cụm | 🔴 chia ước lệ (không rõ số cụm thật) | 552 | 🟢 ~550 (thật) |
| The Opus One | 4 | 🟢 4 (thật: OS1/OS2/OS3/OS5) | 2.084 | 🟢 Dùng ĐÚNG số tầng×căn/tầng thật từng tòa: OS1=34×17=578, OS2=32×15=480, OS3=32×14=448, OS5=34×17=578 (nguồn onehousing.vn — 1 nguồn khác cho tổng 1.952, lệch ~6%, ưu tiên số chi tiết từng tòa vì cụ thể/kiểm chứng được hơn) |

`units_per_floor` trong `dim_zone_master` **dẫn xuất trực tiếp** từ (số căn thật
của zone ÷ `total_floors`) thay vì random độc lập, đảm bảo 2 trường này luôn nhất
quán với số căn thực sinh ra — trừ 8 zone biệt thự (`LOW_RISE_VILLA`), nơi khái
niệm "tầng của cả zone" không áp dụng nên `total_floors`/`units_per_floor` được
ghi **NULL** thay vì một số sai (xem mục 8.4).

## 3. Nguồn dữ liệu THẬT đã cào (WebSearch, truy cập 2026-09-29)

| # | Chủ đề | Số liệu | Nguồn (URL) |
|---|---|---|---|
| 1 | Cấu trúc phân khu (đợt 1) | Rainbow 17 tòa; Origami 21 tòa/~12.000 căn; Beverly 6 tòa; Manhattan ~550 thấp tầng; Glory Heights riêng biệt; Opus One mới 2026 | reb.vn/thong-tin-cac-phan-khu-thuoc-vinhomes-grand-park-tp-thu-duc; vinhomes.vn |
| 2 | Cấu trúc phân khu (đợt 2 — bổ sung) | Rainbow ~10.343-10.435 căn; Beverly 5.088 căn (cả cụm); Glory Heights 5 tòa (24-39 tầng), ~3.450-3.620 căn; Opus One 4 tòa (OS1-OS3,OS5), 1.952-2.084 căn tùy nguồn; tổng VGP "hơn 44.000 sản phẩm BĐS" (không riêng căn hộ) | market.vinhomes.vn/blog/the-rainbow-vinhomes-grand-park; vinhomes.vn/vi/tong-quan-ve-du-an-vinhomes-grand-park-quan-9; cafeland.vn (Beverly, Glory Heights); onehousing.vn/blog/du-an-the-opus-one-vinhomes-grand-park-co-may-toa-va-bao-nhieu-can-ho |
| 3 | Mật độ tòa điển hình | 25-35 tầng phổ biến; 19-30 căn/tầng tùy tòa | market.vinhomes.vn/blog/can-ho-vinhomes-grand-park |
| 4 | Tình trạng mở bán 2026 | The Opus One còn giỏ hàng sơ cấp, chiết khấu tới 23,8% | market.vinhomes.vn; canho.com.vn/vinhomes-grand-park |
| 5 | Hạ tầng (Vành đai 3, Metro số 1/7, Cao tốc Long Thành) | Xem chi tiết trạng thái/tiến độ trong `dim_infrastructure_assets` | tuoitre.vn; plo.vn; znews.vn; reb.vn |
| 6 | Lãi suất vay mua nhà 2026 | Techcombank từ 3,99%; VPBank ~13,2%; MB 8,5-9,5%; Vietcombank từ 9,6%; BIDV 9,7-13,5% | techcombank.com; bidv.com.vn; vietnamnet.vn |
| 7 | Thu nhập hộ gia đình | TP.HCM 27,5 triệu/tháng/hộ (nguồn thứ cấp Q&Me); GSO 2024: 5,4 triệu/người/tháng | tuoitre.vn; nso.gov.vn |
| 8 | Giá bán lại thứ cấp | VGP chung 43,3-80,9 triệu/m²; Rainbow 42-55; Glory Heights 53,2-77,7 | batdongsan.com.vn (3 trang) |
| 9 | Đại lý phân phối | Khải Hoàn Land (Platinum), Đông Tây Land (Platinum Plus), tổng 63 đại lý | vinhomes.vn/vi/danh-sach-dai-ly-chinh-thuc-phan-phoi-du-an-glory-heights-vinhomes-grand-park |

**Lưu ý độ tin cậy**: kết quả WebSearch (snippet tổng hợp), không phải crawl từng
tin đăng. Một số con số (Rainbow, Beverly, Glory Heights) có 2-3 nguồn thứ cấp lệch
nhau nhẹ (không có 1 nguồn CĐT duy nhất, chính thức, đầy đủ) — đã ghi rõ khoảng dao
động và cách chọn giá trị đại diện ở mục 2.

## 4. Nguồn CÀO THẬT vs MOCK theo từng bảng

🟢 cào thật · 🟡 mock có căn cứ/trong khoảng thật · 🔴 mock hoàn toàn.

| Bảng | Tóm tắt nguồn |
|---|---|
| `snapshot_manifest`, `semantic_config` | 🔴 100% mock — meta nội bộ |
| `dim_date` | 🔴 sinh thuật toán |
| `dim_project_profile` (1 dòng, `project_key=300`) | 🟢 tên, vị trí, CĐT · 🟡 segment/construction_status/handover_date/partner_bank là giá trị **tổng hợp** từ 6 phân khu (mục 1.1) — chi tiết thật từng phân khu nay ở `dim_zone_master` |
| `dim_zone_master` (61 dòng, `zone_key` 301-361) | 🟢 số tòa Rainbow/Origami/Beverly/Glory Heights/Opus One (thật) · 🟢 số căn/tòa Opus One (thật, chi tiết từng tòa) · 🟡 số căn/tòa các phân khu còn lại (chia đều theo tổng phân khu) · 🔴 số cụm Manhattan (ước lệ), tên tòa cụ thể · 8 cột **MỞ RỘNG** (`sub_project_*`, `segment`, `construction_status`, `is_sales_permit_issued`, `is_bank_guarantee_issued`, `expected_handover_date` — chuyển xuống từ `dim_project_profile` cũ; `is_bank_guarantee_issued=FALSE` ở Manhattan là kịch bản cấy tay, mục 5) |
| `dim_unit_master` | 🟡 `net_area_m2` hiệu chỉnh theo giá thật · 🔴 toàn bộ thuộc tính còn lại |
| `dim_sales_channel` | 🟢 tên + hạng Khải Hoàn Land/Đông Tây Land · 🔴 phần còn lại |
| `dim_infrastructure_assets` | 🟢 phần lớn · 🔴 % Cao tốc Long Thành (ước lượng) |
| `fact_unit_inventory_snapshot`, `fact_unit_price_history` | 🔴 100% mock — CRM nội bộ |
| `fact_sales_funnel_daily`, `fact_sales_channel_performance` | 🔴 100% mock |
| `dim_secondary_market_comps` | 🟢 khoảng giá Rainbow/Glory Heights · 🔴 4 phân khu còn lại |
| `fact_market_macro_monthly` | 🟢 lãi suất, thu nhập · 🔴 MOI/absorption (công thức tự dựng) |
| `dm_unit_friction_diagnostics` | 🔴 derived 100% — tính bởi **2 pipeline độc lập** (Python + dbt/SQL), khớp tuyệt đối (mục 6) |
| `bridge_unit_channel_history` (MỞ RỘNG) | 🔴 100% mock — không có trong schema gốc |
| `fact_funnel_attribution` (MỞ RỘNG) | 🔴 100% mock — không có trong schema gốc, `attribution_model_default=LINEAR` **chưa được phê duyệt** (mục 8.5) |

## 5. Kịch bản benchmark cấy tay

7/8 mã nguyên nhân tự nhiên xuất hiện ở quy mô 33,6k (dù `SECONDARY_ARBITRAGE` khá
mỏng — chỉ 4 dòng). Riêng `LEGAL_PERMIT_BARRIER` vẫn cấy tay 100% (cờ pháp lý cấp
phân khu, xem lý do ở REPORT.md mục 3.1):

- `is_bank_guarantee_issued = FALSE` cho các zone thuộc phân khu **The Manhattan**
  (cột này ở cấp `dim_zone_master` từ sau khi gộp `project_key` — mục 1.1).
- Ép 2 căn đầu tiên của phân khu này không bao giờ bán được →
  **12 dòng `LEGAL_PERMIT_BARRIER`** (2 căn × 6 kỳ) trong `dm_unit_friction_diagnostics.csv`.

## 6. dbt project (`../dbt_vgp/`)

dbt project thật (không chỉ tài liệu), đọc trực tiếp 17 CSV qua DuckDB
(`external_location`). Gồm **2 mart**:
1. `dm_unit_friction_diagnostics` — tái hiện ma trận 8 nguyên nhân bằng SQL thuần,
   đối chiếu khớp tuyệt đối với bản Python (test `assert_dbt_matches_python_diagnostics`).
2. `mart_channel_attribution_performance` — tổng hợp hiệu suất từng sàn phân phối
   từ Bridge + Attribution (số căn đang/đã từng giao, số touchpoint và tổng trọng
   số đóng góp attribution, tỷ lệ chuyển đổi). Không dùng lại logic chẩn đoán —
   góc nhìn độc lập.

Cộng 3 staging model mở rộng (`stg_snapshot_manifest`, `stg_bridge_unit_channel_history`,
`stg_fact_funnel_attribution`), 1 model helper `int_active_snapshot` (nguồn duy
nhất cho khái niệm "kỳ active"), và các test ràng buộc nghiệp vụ (đúng 1 dòng
`is_current`/căn cho Bridge; `attribution_weight` trong (0,1] và tổng trọng số
theo căn ≈ 1.0 cho Attribution; đúng 1 kỳ `is_active`/lần cho snapshot_manifest).

`dbt build` → **68/68 PASS** (17 view + 2 table model, 49 test).

**Đường dẫn tương đối (portable)**: `_sources.yml`, `profiles.yml`,
`generate_vgp_mock.py`, `build_benchmark.py` dùng đường dẫn tương đối/tự suy từ vị
trí file (không hardcode đường dẫn tuyệt đối) — đã verify bằng cách copy toàn bộ
`2509_VinGrandPark/` sang đường dẫn khác hoàn toàn rồi chạy lại cả 3 bước
(generator, `dbt build`, `build_benchmark.py`), PASS 100% không cần sửa gì. Chỉ
cần giữ nguyên cấu trúc thư mục con (`data/`, `dbt_vgp/`, `document/`, `warehouse/`
cùng cấp) và luôn `cd dbt_vgp` trước khi chạy `dbt build`.

Xem [`../dbt_vgp/README.md`](../dbt_vgp/README.md) để biết chi tiết cấu trúc,
grain, khóa nối, và quy ước "snapshot active"/hợp đồng khóa Central DWH.

## 7. Bộ câu hỏi-SQL chuẩn — `18_benchmark_gold_sql.csv`

**32 câu hỏi** (28 gốc + 3 câu #29-31 đọc trực tiếp từ mart
`mart_channel_attribution_performance` qua ATTACH vào `dbt_vgp/vgp.duckdb` + 1 câu
#32 kiểm tra khái niệm kỳ active vs kỳ mới nạp). Các câu #6, #8, #11, #19, #21 dùng
`dim_zone_master`/`dim_secondary_market_comps.sub_project_*` thay vì
`dim_project_profile` để lấy thông tin phân khu (do gộp `project_key`, mục 1.1).
Các câu #6-8, #15, #19, #22, #24 tra cứu **động** kỳ active qua subquery
`snapshot_manifest WHERE is_active` — không hardcode ngày. Chạy thật bằng DuckDB,
phủ đủ 17/17 bảng gốc + mart consolidation, kết quả hiện tại **32/32 OK**.

**Lưu ý**: câu #29-31 cần chạy `dbt build` trong `../dbt_vgp/` trước (để
`vgp.duckdb` tồn tại), nếu không `build_benchmark.py` sẽ cảnh báo rõ ràng thay vì
tự bịa kết quả.

## 8. Giới hạn cần lưu ý

### 8.1. Giới hạn về phạm vi & nguồn dữ liệu

1. **33.619 căn là quy mô thật CỦA 6 PHÂN KHU NÀY**, không phải toàn bộ VGP
   (~44.000, trải trên 71 tòa gồm nhiều phân khu khác không được mô hình hóa ở đây).
2. Một số tổng phân khu (Rainbow, Beverly, Glory Heights) là **giá trị trung bình
   từ các nguồn thứ cấp lệch nhau**, không phải số liệu CĐT công bố chính thức 1
   nguồn duy nhất — sai số hợp lý có thể ±5-10%.
3. Số căn/tòa của Rainbow/Origami/Beverly/Glory Heights là **chia đều theo tổng
   phân khu** (không có số liệu riêng từng tòa như Opus One) — thực tế các tòa
   trong cùng phân khu có thể không đồng đều.
4. Mọi số liệu 🔴/🟡 là **giả định phục vụ demo/test**, không dùng cho quyết định
   kinh doanh thật.

### 8.2. Đơn giản hóa có chủ đích

5. Peer Group dùng 2 tầng (cùng phân khu+loại căn+nhóm tầng → fallback cùng
   phân khu+loại căn) thay vì 6 tiêu chí gốc — xem REPORT.md mục 3.6. Quyết định
   giữ nguyên vì dễ đọc/bảo trì và không ảnh hưởng đáng kể ở quy mô này.

### 8.3. Phần mở rộng ngoài schema gốc

6. Bridge (`bridge_unit_channel_history`) + Attribution (`fact_funnel_attribution`)
   không có trong tài liệu đặc tả gốc.
7. `snapshot_manifest.is_active` và `semantic_config.active_snapshot_date_key`
   cũng là mở rộng ngoài schema gốc (mục 1.2).
8. `dim_zone_master.sub_project_*` (8 cột) và `dim_secondary_market_comps.sub_project_*`
   (2 cột) là mở rộng phát sinh từ việc gộp `project_key` theo hợp đồng khóa
   Central DWH (mục 1.1).

### 8.4. Audit log — bug đã phát hiện & sửa

9. `fact_sales_channel_performance.avg_days_to_sell` từng bị tính nhầm bằng
   `mean(unsold_days_dom)` (công thức DOM lũy kế `snapshot_date - release_date`)
   thay vì công thức riêng của chính nó theo docx (`sold_date - release_date`) —
   2 công thức khác nhau bị dùng lẫn, khiến giá trị bị thổi phồng tới ~2.130 ngày
   trung bình thay vì ~144 ngày thực tế. Đã sửa trong `generate_vgp_mock.py`.
   Không ảnh hưởng `unsold_days_dom` gốc, `is_overdue_flag`, hay
   `dm_unit_friction_diagnostics` (cả 3 chỉ dùng DOM cho căn AVAILABLE, nơi công
   thức docx gốc vốn đã đúng).
10. `dim_zone_master.total_floors`/`units_per_floor` của 8 zone biệt thự (Manhattan
    Cum) từng hardcode `4`/`1` (ngụ ý 4 căn/zone) trong khi mỗi zone thực có 69 căn
    — phá vỡ invariant "derive từ số căn thật". Docx gốc mô tả 2 trường này là
    khái niệm tòa apartment và để `total_floors` nullable, không có hướng dẫn
    tường minh cho villa (spec-gap, không phải lỗi cố ý). Đã sửa: ghi **NULL** cho
    8 zone này (đúng tinh thần docx) thay vì hardcode gây hiểu nhầm.
    `dim_unit_master.floor_number` cấp căn giữ nguyên (docx bắt buộc không null).
11. Công thức "đổi sàn phân phối" trong Bridge table giả định `channel_key` liên
    tiếp 1..5 — vỡ khi re-key sang 3001-3005 theo hợp đồng khóa Central DWH
    (mục 1.1). Đã sửa bằng ánh xạ qua vị trí trong mảng.

### 8.5. Chưa xác minh được / cần theo dõi

12. **`attribution_score`** — `SNAPSHOT_RULES.md` (áp dụng chung cho cả 5 Project
    Data Pack) yêu cầu *"8 mã nguyên nhân cốt lõi; `attribution_score` cộng =
    1.000 / chẩn đoán"*. Đã grep cả 3 bản docx cục bộ (v0/v2/v3) — từ khóa này
    **không xuất hiện** ở đâu cả; nguồn thẩm quyền thật
    (`data-warehouse-schema.md v3.1.0`, `DATA_Warehouse_Plan_30-09.md`) **không có
    trên máy**. Không tự thêm cột `attribution_score` bịa vào
    `dm_unit_friction_diagnostics` vì thiếu đặc tả gốc. Tạm coi rule này đã đáp
    ứng về tinh thần qua `fact_funnel_attribution.attribution_weight` (cộng
    ≈1.000 theo unit/outcome_date, test `assert_attribution_weight_sums_to_one`
    PASS) — đây là **suy đoán hợp lý, không phải xác nhận chắc chắn**, cần đối
    chiếu lại nếu có được spec v3.1.0 thật.
13. **2 config `semantic_config` còn `PENDING`, CHƯA được phê duyệt chính thức**
    (không tự ý đổi thành `APPROVED` — ngoài thẩm quyền):
    - `defect_unit_share_assumption = 0.18` — chi phối tỷ lệ căn bị gán khuyết
      tật cấu trúc khi sinh toàn bộ 33.619 căn (`dim_unit_master`), lan sang
      `SEVERE_PHYSICAL_DEFECT` (158 dòng chẩn đoán).
    - `attribution_model_default = LINEAR` — chi phối 100% `fact_funnel_attribution`
      (19.907 dòng) + mart `mart_channel_attribution_performance` + benchmark #27-31.

    dbt hiện **không có cơ chế nào kiểm tra `approval_status`**. **Không dùng 2
    phần dữ liệu trên làm baseline báo cáo chính thức** cho tới khi có phê duyệt
    thật từ chủ sở hữu hợp đồng schema.

## 9. Danh sách file

| File | Số dòng | Vai trò |
|---|---:|---|
| 01_snapshot_manifest.csv | 6 | snapshot_manifest (có cột `is_active` mở rộng) |
| 02_semantic_config.csv | 12 | semantic_config (2 dòng còn PENDING, mục 8.5) |
| 03_dim_date.csv | 730 | dim_date |
| 04_dim_project_profile.csv | 1 | dim_project_profile (1 dòng duy nhất, `project_key=300`) |
| 05_dim_zone_master.csv | 61 | dim_zone_master (+8 cột mở rộng thuộc tính phân khu) |
| 06_dim_unit_master.csv | 33.619 | dim_unit_master |
| 07_dim_sales_channel.csv | 5 | dim_sales_channel (`channel_key` 3001-3005) |
| 08_dim_infrastructure_assets.csv | 4 | dim_infrastructure_assets (`infra_key` 3101-3104) |
| 09_fact_unit_inventory_snapshot.csv | 200.545 | fact_unit_inventory_snapshot |
| 10_fact_sales_funnel_daily.csv | 59.832 | fact_sales_funnel_daily |
| 11_fact_unit_price_history.csv | 454 | fact_unit_price_history |
| 12_dim_secondary_market_comps.csv | 360 | dim_secondary_market_comps (+2 cột `sub_project_*`) |
| 13_fact_market_macro_monthly.csv | 21 | fact_market_macro_monthly |
| 14_fact_sales_channel_performance.csv | 30 | fact_sales_channel_performance (grain (kỳ×sàn) = 6×5 sau khi `project_key` thành hằng số) |
| 15_dm_unit_friction_diagnostics.csv | 2.144 | dm_unit_friction_diagnostics (cả 6 kỳ) |
| 16_bridge_unit_channel_history.csv | 36.975 | **Bridge table (mở rộng)** |
| 17_fact_funnel_attribution.csv | 19.907 | **Attribution table (mở rộng)** |
| 18_benchmark_gold_sql.csv | 32 | Bộ câu hỏi-SQL chuẩn |
| generate_vgp_mock.py | — | Script sinh 17 bảng (vector hóa, seed=42) |
| build_benchmark.py | — | Script sinh bộ câu hỏi-SQL chuẩn (DuckDB) |
| `../dbt_vgp/` | — | dbt project thật (68/68 model+test PASS, 2 mart) |
| `../warehouse/` | — | Hợp đồng khóa Central DWH (`id_registry.json`, `SNAPSHOT_RULES.md`) |
