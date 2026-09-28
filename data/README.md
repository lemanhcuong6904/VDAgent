# Bộ dữ liệu mock — Vinhomes Grand Park (VGP)

Bộ dữ liệu này mô phỏng 15 bảng trong `data-warehouse-schema-v3.docx` (VDAGENT,
Dimensional Star Schema) áp cho dự án thật **Vinhomes Grand Park**, TP. Thủ Đức,
TP.HCM. Sinh ngày 2026-09-29 bằng script [`generate_vgp_mock.py`](generate_vgp_mock.py)
(Python, `random.seed(42)` / `np.random.seed(42)` — tái tạo được y hệt nếu chạy lại
script với cùng seed).

## 1. Phạm vi & quy ước

- **6 phân khu** (mỗi phân khu = 1 `project_key`, xem mục 2 phần "Vì sao tách theo
  phân khu"): The Rainbow, The Origami, The Beverly, Glory Heights, The Manhattan,
  The Opus One.
- **68 tòa/cụm** (`dim_zone_master`) — dùng ĐÚNG số tòa thật đã cào cho Rainbow (17),
  Origami (21), Beverly (6); Glory Heights/Manhattan/Opus One dùng số cụm **ước
  lượng** (8 mỗi phân khu, KHÔNG xác minh được số thật).
- **1.960 căn hộ đại diện** (`dim_unit_master`, ~4,5% quy mô thật ~44.000+ căn của
  VGP — tăng từ 725 căn (~1,6%) theo yêu cầu scale-up; 30 căn/tòa cao tầng, 20
  căn/cụm villa Manhattan).
- **6 kỳ snapshot chốt sổ**: 2026-04-30, 05-31, 06-30, 07-31, 08-31, 09-29 (kỳ mới
  nhất = "hôm nay").
- **Kết quả logic quan trọng**: 5/6 phân khu (Rainbow, Origami, Beverly, Glory
  Heights, Manhattan) đã bàn giao 2020-2022 nên tại kỳ chốt 2026-09-29 gần như đã
  bán hết tồn kho sơ cấp (đúng thực tế thị trường của một dự án đã ra sổ nhiều năm).
  Phần lớn 67 dòng `dm_unit_friction_diagnostics` (căn tồn >90 ngày) rơi vào
  **The Opus One** — phân khu duy nhất còn đang mở bán sơ cấp thật vào năm 2026 —
  cộng thêm 2 căn "kẹt pháp lý" cấy tay tại The Manhattan (xem mục 4).
- **Bản cập nhật lần 2**: phát hiện và sửa 1 bug nghiêm trọng (đơn giá bị thiếu
  nhân 1.000.000 khi tính `asking_price_vnd`); cấy tay đủ 8/8 kịch bản nguyên nhân
  (mục 4); sửa lại công thức Peer Group cho đúng 6 tiêu chí gốc (mục 4.1 tài liệu
  gốc); bổ sung bộ câu hỏi-SQL chuẩn `16_benchmark_gold_sql.csv` (mục 6).
- **Bản cập nhật lần 3**: scale số căn hộ từ 725 → 1.960 theo yêu cầu, đồng thời
  đổi cách sinh `dim_zone_master` sang dùng đúng số tòa thật đã cào cho 3 phân khu
  có nguồn xác thực (Rainbow/Origami/Beverly) thay vì chỉ lấy mẫu 3 tòa/phân khu
  như bản trước.

## 2. Nguồn dữ liệu THẬT đã cào (WebSearch, truy cập 2026-09-29)

| # | Chủ đề | Số liệu/thông tin lấy được | Nguồn (URL) |
|---|---|---|---|
| 1 | Phân khu VGP | The Rainbow (17 tòa, 25-35 tầng, mở bán đầu tiên); The Origami (21 tòa, ~12.000 căn, 5 cụm S6-S10); The Beverly (6 tòa, gồm cụm Beverly Solari); The Manhattan (~550 sản phẩm thấp tầng, KHÔNG phải chung cư); Glory Heights (phân khu riêng); The Opus One (mới, đang mở bán 2026, giá studio từ 2,6 tỷ) | reb.vn/thong-tin-cac-phan-khu-thuoc-vinhomes-grand-park-tp-thu-duc; vinhomes.vn/vi/the-origami-vinhomes-grand-park-tinh-than-nhat-giua-long-sai-gon; market.vinhomes.vn/mua-ban-can-ho-chung-cu-vinhomes-grand-park |
| 2 | Tình trạng mở bán 2026 | The Opus One còn giỏ hàng sơ cấp, chiết khấu tới 23,8% | market.vinhomes.vn/mua-ban-can-ho-chung-cu-vinhomes-grand-park; canho.com.vn/vinhomes-grand-park |
| 3 | Vành đai 3 TP.HCM (đoạn Thủ Đức) | Tiến độ ~82-83%, mục tiêu thông xe 6/2026 | tuoitre.vn (tien-do-vanh-dai-3-tphcm...20260424); plo.vn/du-an-vanh-dai-3-tphcm-thong-xe-toan-tuyen-vao-thang-6-2026-post846366.html |
| 4 | Metro số 1 Bến Thành - Suối Tiên | Đã vận hành thương mại từ cuối 2024 | reb.vn/huong-dan-di-metro-so-1-ben-thanh-suoi-tien |
| 5 | Metro số 7 (Tân Kiên - VGP) | Mới ở giai đoạn đề xuất PPP, chưa khởi công (điều chỉnh hướng tuyến 2/2026) | tuoitre.vn (lien-danh-nha-dau-tu-de-xuat-nghien-cuu-metro-so-7); plo.vn/dieu-chinh-huong-tuyen-metro-so-7-tan-kien-vinhomes-grand-park-post901731.html |
| 6 | Cao tốc TP.HCM - Long Thành - Dầu Giây (mở rộng) | Đang thi công (khởi công 8/2025), mục tiêu hoàn thành cơ bản 12/2026 | znews.vn/hoan-tat-mo-rong-cao-toc-tphcm-long-thanh-dau-giay-trong-nam-2026-post1576311.html |
| 7 | Lãi suất vay mua nhà 2026 | Techcombank ưu đãi từ 3,99%/năm (24 tháng đầu); VPBank ~13,2%/năm; MB 8,5-9,5%/năm; Vietcombank ưu đãi từ 9,6%/năm; BIDV 9,7-13,5%/năm, thả nổi có thể tới ~16-17%/năm | techcombank.com/thong-tin/thong-bao/uu-dai-lai-vay-mua-ngay-nha-moi; bidv.com.vn/bidv/bidv-blog/tin-dung/lai-suat-vay-mua-nha; vietnamnet.vn/lai-suat-vay-bat-dong-san-tang-cao-sau-uu-dai-co-the-toi-16-nam-2548879.html |
| 8 | Thu nhập hộ gia đình | TP.HCM: 27,5 triệu đồng/tháng/hộ (dẫn đầu cả nước, nguồn Q&Me qua báo); toàn quốc GSO 2024: 5,4 triệu/người/tháng | tuoitre.vn/thu-nhap-ho-gia-dinh-tai-tphcm-dan-dau-ca-nuoc-post902361.html; nso.gov.vn/tin-tuc-thong-ke/2025/05/... |
| 9 | Giá bán lại thứ cấp | VGP chung: 43,3-80,9 triệu/m² (779 tin, T9/2026); The Rainbow: 42-55 triệu/m²; Glory Heights: 53,2-77,7 triệu/m² | batdongsan.com.vn/ban-can-ho-chung-cu-vinhomes-grand-park; batdongsan.com.vn/ban-can-ho-chung-cu-the-rainbow-vinhomes-grand-park; batdongsan.com.vn/ban-can-ho-chung-cu-glory-heights-vinhomes-grand-park |
| 10 | Đại lý phân phối chính thức | Khải Hoàn Land (Platinum), Đông Tây Land (Platinum Plus), tổng 63 đại lý | vinhomes.vn/vi/danh-sach-dai-ly-chinh-thuc-phan-phoi-du-an-glory-heights-vinhomes-grand-park |

**Lưu ý về độ tin cậy:** đây là kết quả tra cứu qua WebSearch (snippet tổng hợp),
KHÔNG phải crawl trực tiếp từng tin đăng cụ thể (không lấy được ngày đăng/người đăng
riêng lẻ trên Batdongsan/Chotot — search chỉ trả về số liệu tổng hợp trang). Số liệu
mục 7, 8 nên được đối chiếu lại nếu dùng cho quyết định thật. Không tìm được nguồn
đáng tin cậy cho: danh mục xác nhận pháp lý từng phân khu từ Sở Xây dựng TP.HCM,
phân loại phân khúc chính thức từ CBRE/Savills/DKRA, tên đầy đủ các đại lý CenLand/
DKRA/Hưng Thịnh Land cho riêng VGP.

## 3. Chi tiết theo từng bảng CSV

### 01_snapshot_manifest.csv, 02_semantic_config.csv
🔴 Mock toàn bộ — đây là bảng meta nội bộ hệ thống, không tồn tại nguồn public.
`semantic_config` mã hóa lại các ngưỡng nghiệp vụ nêu ở mục 4 tài liệu gốc
(`overdue_threshold_days=90`, `peer_area_tolerance_pct=0.10`...). Riêng
`defect_unit_share_assumption` (18%) là **tự hiệu chỉnh** vì tài liệu gốc có ẩn số
trong ảnh không đọc được — đánh dấu `approval_status=PENDING` để phân biệt với các
ngưỡng lấy đúng từ văn bản (`APPROVED`).

### 03_dim_date.csv
🔴 Sinh thuần túy theo lịch Gregorian (2025-01-01 → 2026-12-31), không cần crawl.

### 04_dim_project_profile.csv
🟢 CÀO THẬT: `project_name`, số tòa mỗi phân khu (ghi trong cột note của script),
`construction_status`/thời điểm mở bán của The Opus One (đang xây, mở bán 2026),
`developer_name`/`developer_tier`/`developer_origin` (Vingroup, Tier 1, Domestic —
kiến thức phổ thông đã xác thực).
🟡 MOCK có căn cứ: khoảng giá `segment` suy từ tên dòng sản phẩm marketing (Sapphire/
Ruby/Diamond) — KHÔNG phải phân loại chính thức CBRE/Savills.
🔴 MOCK không có nguồn xác nhận: `is_sales_permit_issued`/`is_bank_guarantee_issued`
(gán TRUE cho 5/6 phân khu — suy luận hợp lý vì đang bán/đã bán công khai, nhưng
KHÔNG tìm được danh mục xác nhận trực tiếp từ Sở Xây dựng TP.HCM; riêng **The
Manhattan** có `is_bank_guarantee_issued = FALSE` — đây là **kịch bản benchmark cấy
tay**, không phải phát hiện thật, xem mục 4), `expected_handover_date` của 5 phân
khu cũ (suy ngược từ thứ tự mở bán thực tế, không phải ngày chính xác đã công bố),
`distance_to_primary_infra_m` (giá trị số cụ thể, dù việc VGP gần Metro số 1 là thật).

### 05_dim_zone_master.csv
🟢 CÀO THẬT: **số lượng tòa** của Rainbow (17), Origami (21), Beverly (6) — dùng
đúng số thật đã cào làm `ZONE_COUNT` để sinh đủ số dòng (không còn lấy mẫu 3 tòa
như bản trước); `zone_type` villa/thấp tầng cho Manhattan.
🔴 MOCK: **số lượng tòa** của Glory Heights/Manhattan/Opus One (8 mỗi phân khu —
ước lượng, KHÔNG xác minh được số cụm/tòa thật); tên tòa cụ thể (`Toa Rainbow 1`...)
là đặt tên đại diện theo số thứ tự, KHÔNG xác minh được tên tòa thật từng cái;
`total_floors`, `units_per_floor`, `passenger_elevators`, `handover_standard` —
ước lượng theo mặt bằng chung phân khúc cao tầng Vinhomes (bàn giao "hoàn thiện cơ
bản" là kiến thức phổ thông thị trường, không phải số liệu công bố riêng cho VGP).

### 06_dim_unit_master.csv
🔴 Mock gần như toàn bộ — không có nguồn public nào cung cấp mặt bằng tầng/thuộc
tính chi tiết từng căn (khoảng cách phòng rác, căn kề thang máy, phòng tối...).
`net_area_m2` được hiệu chỉnh theo khoảng giá thật đã cào (VD studio Origami ~29m²
suy từ giá 1,75-1,85 tỷ ÷ ~61 triệu/m²). Tỷ lệ căn lỗi cấu trúc (18%) và tỷ lệ căn
lỗi nhưng không giảm giá bù trừ (45%) là **hằng số tự đặt**, mô phỏng đúng quy tắc
định tính ở mục 5.1 tài liệu gốc nhưng KHÔNG lấy đúng % gốc (ảnh không đọc được).

### 07_dim_sales_channel.csv
🟢 CÀO THẬT: tên "Khải Hoàn Land", "Đông Tây Land" và xếp hạng Platinum/Platinum
Plus của họ.
🔴 MOCK: `active_brokers_count` (không public), "Saigon Real" gán TIER_2_GENERAL
(chưa xác minh cấp bậc chính thức), 1 đại lý hoàn toàn hư cấu
(`AGENCY-GENERIC-01`) thêm vào chỉ để tạo đa dạng dữ liệu test.

### 08_dim_infrastructure_assets.csv
🟢 CÀO THẬT phần lớn: `infra_name`, `lifecycle_stage`, mốc năm hoàn thành của cả 4
công trình (Metro số 1, Vành đai 3, Metro số 7, Cao tốc Long Thành).
🟡 MOCK: giá trị số `construction_progress_pct` cụ thể của Vành đai 3 (82.5 — lấy
đúng khoảng thật) nhưng của Cao tốc Long Thành (70.0) là **ước lượng riêng** vì
nguồn chỉ mô tả định tính ("đang thảm nhựa"), không có % chính xác.

### 09_fact_unit_inventory_snapshot.csv, 11_fact_unit_price_history.csv
🔴 Mock toàn bộ — đây chính là dữ liệu CRM/vận hành nội bộ CĐT, không thể cào theo
đánh giá ở phần trước. Logic sinh: mỗi căn được gán một "thời gian bán dự kiến"
(phân phối exponential, trung bình dài hơn nếu căn có lỗi-không-giảm-giá/hướng Tây/
hoa hồng thấp) — mô phỏng đúng ý mục 5.1 "tương quan kinh tế có tính tất định" của
tài liệu gốc, không phải số liệu thật.

### 10_fact_sales_funnel_daily.csv, 14_fact_sales_channel_performance.csv
🔴 Mock toàn bộ — dữ liệu hành vi khách hàng/hiệu suất sàn hoàn toàn nội bộ CRM,
KHÔNG có nguồn public nào thay thế được (đã đánh giá ở phần trả lời trước). Riêng
`fact_sales_channel_performance` được **tổng hợp lại (aggregate) từ chính
`fact_unit_inventory_snapshot`** đã sinh, không phải random độc lập, để đảm bảo nhất
quán số học giữa 2 bảng.

### 12_dim_secondary_market_comps.csv
🟢 CÀO THẬT (khoảng giá): The Rainbow 42-55 triệu/m², Glory Heights 53,2-77,7
triệu/m² lấy đúng từ batdongsan.com.vn.
🟡 MOCK trong khoảng thật: từng bản ghi giao dịch cụ thể (comp_id, ngày, hướng ban
công...) là random nhưng được **kẹp trong khoảng giá thật đã cào**.
🔴 MOCK không có nguồn riêng: khoảng giá của The Origami, The Beverly, The Manhattan,
The Opus One (đặc biệt Opus One — dự án mới 2026, thực tế CHƯA có giao dịch thứ cấp
thật vì chưa bàn giao, nên toàn bộ comp của phân khu này là giả định thuần túy phục
vụ test).

### 13_fact_market_macro_monthly.csv
🟢 CÀO THẬT: `floating_mortgage_rate_pct` bình quân (10,5%/năm — khảo sát 5 ngân
hàng), `median_household_income_vnd` (330 triệu/năm — từ số liệu TP.HCM đã cào).
🔴 MOCK: `months_of_inventory_moi`, `absorption_rate_pct` — không có báo cáo CBRE/
Savills/VARS công khai đầy đủ cho riêng khu vực Thủ Đức/VGP, nên được sinh theo
**công thức tương quan nghịch với lãi suất** (đúng quy tắc mục 5.1 tài liệu gốc)
thay vì số liệu thật. `macro_price_to_income_ratio` tính từ mức giá điển hình
giả định (60 triệu/m² × 65m²), không phải số liệu khảo sát thật.

### 15_dm_unit_friction_diagnostics.csv
🔴 Tính toán lại (derived) từ toàn bộ các bảng mock ở trên, áp đúng thứ tự ưu tiên
ma trận 8 nguyên nhân ở mục 4.3 tài liệu gốc, với **Peer Group tính theo đúng 6 tiêu
chí gốc** (mục 4.1): cùng dự án, cùng đợt mở bán (`launch_batch_id`), cùng loại
hình, dung sai diện tích ±10%, cùng nhóm tầng/hướng mát-nóng, và cơ chế "mở rộng dần"
khi không đủ cỡ mẫu tối thiểu (bỏ tiêu chí đợt mở bán trước, rồi bỏ tiêu chí tầng/
hướng, đúng tinh thần "mở rộng sang tầng lân cận, gắn cờ cảnh báo" của tài liệu gốc).
Có thêm 1 mã `MULTI_FACTOR_UNCLASSIFIED` **không có trong tài liệu gốc** — tự thêm
làm giá trị dự phòng khi một căn tồn kho quá hạn nhưng không khớp rõ ràng bất kỳ điều
kiện nào trong 8 quy tắc gốc; cần coi đây là điểm cần rà soát thủ công, không phải
cause code chính thức của schema. Cả **8/8 mã nguyên nhân gốc đều đã xuất hiện** nhờ
kịch bản cấy tay ở mục 4.

## 4. Kịch bản benchmark cấy tay (đảm bảo phủ đủ 8/8 mã nguyên nhân)

Vì mô phỏng ngẫu nhiên thuần túy ban đầu (khi dataset còn ~30 căn tồn kho quá hạn)
chỉ tình cờ trúng 3-4/8 mã, tôi đã **chủ động ghi đè** 1 căn cụ thể cho mỗi mã còn
thiếu. Sau khi scale lên 1.960 căn (67 dòng chẩn đoán), 4/5 mã cấy tay đó đã có thêm
**ca tự nhiên** trùng điều kiện nhờ cỡ mẫu lớn hơn (số liệu chi tiết theo từng mã ở
`REPORT.md` mục 3.1) — riêng `LEGAL_PERMIT_BARRIER` vẫn phụ thuộc 100% vào cấy tay vì
gắn với cờ pháp lý cấp dự án (chỉ 1/6 phân khu bị đặt `FALSE`). Dữ liệu cấy tay là
**có chủ đích cho mục đích test**, không phải kết quả mô phỏng khách quan — cần phân
biệt rõ với phần dữ liệu sinh ngẫu nhiên còn lại. Căn/dòng gốc bị ghi đè:

| Mã nguyên nhân | Căn/phân khu bị ghi đè | Cách cấy |
|---|---|---|
| `LEGAL_PERMIT_BARRIER` | 2 căn đầu tiên của cụm "Manhattan Cụm 1" (`53-01`, `53-02` — mã căn phụ thuộc `zone_key`, sẽ đổi nếu chạy lại script với cấu trúc zone khác) | Đặt `is_bank_guarantee_issued = FALSE` cho cả phân khu The Manhattan (`04_dim_project_profile.csv`) + ép 2 căn này không bao giờ bán được (`planned_sold_date = None`) |
| `SEVERE_PHYSICAL_DEFECT` | 1 căn Opus One (đã có sẵn, không tạo thêm mã) | Ép `distance_to_trash_room_m = 1.2` và `is_adjacent_elevator = TRUE` (dpen ≥ 55), đồng thời giữ giá ngang mức peer (không giảm bù trừ) |
| `LUMP_SUM_TICKET_BARRIER` | 1 căn 3PN/4PN Opus One | Ép `net_area_m2 = 118`, hướng Nam (tránh dính phạt nhiệt), giá giữ ngang peer — tổng giá vượt ngưỡng PIR ≥ 20 dù đơn giá/m² hợp lý |
| `OVERPRICED_VS_PEER` | 1 căn 2PN Opus One không lỗi | Ép đơn giá = 1,15 × giá bình quân dự án (chênh > 8% so với peer) trong khi không có lỗi vật lý/nhiệt |
| `SECONDARY_ARBITRAGE` | 1 căn 1PN Opus One không lỗi | Ép đơn giá sơ cấp = 1,25 × giá thứ cấp trung bình ước tính của Opus One (chênh ≥ 15%) |
| `EXTREME_THERMAL_EXPOSURE`, `LOW_SALES_INCENTIVE`, `DEEP_FUNNEL_DROP_OFF` | Không cấy tay | Đã tự nhiên xuất hiện đủ từ mô phỏng ngẫu nhiên gốc |

Toàn bộ logic cấy tay nằm trong khối `# 8b. CAY KICH BAN BENCHMARK` của
[`generate_vgp_mock.py`](generate_vgp_mock.py) — sửa/xóa khối đó nếu muốn quay lại
bản mô phỏng 100% ngẫu nhiên (khi đó xác suất đủ 8/8 mã sẽ rất thấp với cỡ mẫu nhỏ).

## 5. Giới hạn cần lưu ý khi dùng bộ dữ liệu này

1. **Quy mô vẫn nhỏ so với thật** (1.960/~44.000+ căn thật, ~4,5%) — đủ để test pipeline/Text-to-SQL,
   không đại diện thống kê cho toàn bộ VGP.
2. **8/8 mã nguyên nhân đã xuất hiện nhưng 5/8 mã cần cấy tay** (mục 4) — nghĩa là
   nếu dùng bộ dữ liệu này để đánh giá khả năng một Agent "tự phát hiện" các kịch bản
   hiếm, cần biết trước những mã nào là cấy tay để không hiểu lầm đó là hành vi nổi
   lên tự nhiên từ dữ liệu thị trường thật.
3. Mọi số liệu đánh dấu 🔴/🟡 trong mục 3 là **giả định phục vụ demo/test**, không
   được dùng làm căn cứ ra quyết định kinh doanh thật.
4. **Bug đã phát hiện và sửa**: bản sinh đầu tiên quên nhân đơn giá (đơn vị "triệu
   đồng/m²" lấy từ dữ liệu cào thật) với 1.000.000 khi tính `asking_price_vnd`,
   khiến `ticket_size_vs_income_ratio` luôn ra 0.0 và `price_spread_vs_peer_pct`
   luôn rỗng. Đã sửa tại 3 điểm tính giá trong `generate_vgp_mock.py` (dòng có
   `* 1_000_000`) — nếu bạn tự sửa/mở rộng script, chú ý giữ đúng quy ước đơn vị này
   (biến nội bộ `ppm2` = triệu đồng/m², chỉ nhân lên VND thật khi ghi ra cột output).
5. File `generate_vgp_mock.py` đi kèm ghi lại toàn bộ logic + hằng số đã dùng —
   nguồn tham chiếu chính xác nhất khi cần tra lại vì sao một giá trị cụ thể ra như
   vậy.

## 6. Bộ câu hỏi-SQL chuẩn (Gold Standard) — `16_benchmark_gold_sql.csv`

Để bộ dữ liệu thực sự dùng được làm benchmark đánh giá Text-to-SQL (đúng mục tiêu
mục 6.2 tài liệu gốc — đo độ chính xác sinh SQL của LLM), tôi đã viết **24 cặp câu
hỏi nghiệp vụ ↔ SQL ↔ kết quả kỳ vọng**, chạy thật bằng DuckDB trực tiếp trên các
CSV ở trên (script [`build_benchmark.py`](build_benchmark.py)) để đảm bảo SQL chạy
được và kết quả là **kết quả thật**, không tự bịa. File có các cột:

- `question_id`, `question_vi` — câu hỏi tiếng Việt.
- `difficulty` — EASY (1 bảng) / MEDIUM (JOIN 2 bảng) / HARD (JOIN ≥2 bảng hoặc
  aggregation/window function phức tạp).
- `join_hop_count` — số bảng phải JOIN, dùng để đo đúng tiêu chí "Single-hop JOIN"
  mà tài liệu gốc đặt mục tiêu tối ưu.
- `tables_used`, `sql` — SQL chuẩn tham chiếu.
- `status`, `expected_row_count`, `expected_result_sample` — kết quả thật (tối đa 8
  dòng mẫu dạng JSON) khi chạy SQL trên bộ dữ liệu này tại thời điểm sinh.

Phân bố độ khó: 5 EASY, 8 MEDIUM, 11 HARD — bao phủ cả 15 bảng gốc và toàn bộ 8 mã
nguyên nhân chẩn đoán (câu hỏi #9-12, #23). **Lưu ý:** nếu bạn chạy lại
`generate_vgp_mock.py` với seed khác hoặc sửa logic sinh dữ liệu, phải chạy lại
`build_benchmark.py` để cập nhật `expected_result_sample` — kết quả kỳ vọng hiện tại
chỉ đúng với đúng bộ CSV đang có trong thư mục này.

## 7. Danh sách file

| File | Số dòng dữ liệu | Bảng tương ứng / vai trò |
|---|---|---|
| 01_snapshot_manifest.csv | 6 | snapshot_manifest |
| 02_semantic_config.csv | 11 | semantic_config |
| 03_dim_date.csv | 730 | dim_date |
| 04_dim_project_profile.csv | 6 | dim_project_profile |
| 05_dim_zone_master.csv | 68 | dim_zone_master |
| 06_dim_unit_master.csv | 1,960 | dim_unit_master |
| 07_dim_sales_channel.csv | 5 | dim_sales_channel |
| 08_dim_infrastructure_assets.csv | 4 | dim_infrastructure_assets |
| 09_fact_unit_inventory_snapshot.csv | 11,611 | fact_unit_inventory_snapshot |
| 10_fact_sales_funnel_daily.csv | 28,487 | fact_sales_funnel_daily |
| 11_fact_unit_price_history.csv | 67 (biến động theo seed) | fact_unit_price_history |
| 12_dim_secondary_market_comps.csv | 210 | dim_secondary_market_comps |
| 13_fact_market_macro_monthly.csv | 21 | fact_market_macro_monthly |
| 14_fact_sales_channel_performance.csv | 180 | fact_sales_channel_performance |
| 15_dm_unit_friction_diagnostics.csv | 67 (biến động theo seed) | dm_unit_friction_diagnostics |
| 16_benchmark_gold_sql.csv | 24 | Bộ câu hỏi-SQL chuẩn (mục 6) |
| generate_vgp_mock.py | — | Script sinh 15 bảng CSV (seed=42, tái tạo được) |
| build_benchmark.py | — | Script sinh bộ câu hỏi-SQL chuẩn từ CSV (dùng DuckDB) |
