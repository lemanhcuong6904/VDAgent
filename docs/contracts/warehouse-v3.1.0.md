# Data contract — VDAgent Data Warehouse v3.1.0

**Phạm vi:** 16 bảng analytical warehouse cho POC Vinhomes Smart City. Nguồn đặc tả cột, kiểu, nullability và khóa: `Data Warehouse Schema (Final).docx`, phiên bản 3.1.0. Nguồn dữ liệu và thứ tự nạp bên dưới là kế hoạch triển khai cho data pack, chưa xác nhận đã crawl hoặc nạp dữ liệu.

**Quy ước:** `Không` = NOT NULL, `Có` = nullable; `PK`, `UK`, `FK` theo tài liệu gốc. Giá dùng VND; diện tích chuẩn là m² thông thủy; mốc POC `2026-06-30`. Các FK bên dưới chỉ nằm **trong warehouse**. `snapshot_id`, `project_id`, `unit_id` là khóa ghép logic với backend, không phải FK xuyên database.

## Danh mục, grain, nguồn và thứ tự nạp

| Thứ tự | Bảng | Grain | Nguồn dự kiến cho data pack | Phụ thuộc chính |
| ---: | --- | --- | --- | --- |
| 01 | `snapshot_manifest` | 1 phiên chốt sổ | Cấu hình snapshot nội bộ | — |
| 02 | `semantic_config` | 1 tham số quy tắc | Ngưỡng nghiệp vụ được duyệt | `snapshot_manifest.semantic_version` phải khớp |
| 03 | `dim_date` | 1 ngày Gregorian | Sinh lịch deterministically | — |
| 04 | `dim_infrastructure_assets` | 1 công trình hạ tầng | Quy hoạch/công bố công khai có nguồn; mock khi thiếu | — |
| 05 | `dim_project_profile` | 1 dự án | Hồ sơ dự án, pháp lý công bố; mock khi thiếu | `primary_infra_id` tham chiếu logic tới hạ tầng |
| 06 | `dim_zone_master` | 1 phân khu/tòa | Hồ sơ dự án, mặt bằng tòa; mock khi thiếu | `dim_project_profile` |
| 07 | `dim_unit_master` | 1 căn vật lý | Mặt bằng/giỏ hàng nội bộ; mock khi thiếu | `dim_project_profile`, `dim_zone_master` |
| 08 | `dim_sales_channel` | 1 sàn/đại lý | CRM hoặc danh mục phân phối; mock khi thiếu | — |
| 09 | `dim_secondary_market_comps` | 1 giao dịch thứ cấp xác thực | Giao dịch xác thực; tin rao chỉ dùng làm tín hiệu tham khảo, mock khi thiếu | Ghép theo thuộc tính so sánh, không có FK |
| 10 | `fact_market_macro_monthly` | 1 thị trường × phân khúc × tháng | Báo cáo thị trường, chỉ số vay/thu nhập; mock khi thiếu | `dim_date` |
| 11 | `fact_unit_price_history` | 1 sự kiện đổi giá căn | Bảng giá/chính sách nội bộ; mock khi thiếu | `dim_unit_master`, `dim_date` |
| 12 | `fact_sales_funnel_daily` | 1 căn × ngày tương tác | CRM, web/app, hồ sơ cọc; mock khi thiếu | `dim_unit_master`, `dim_date` |
| 13 | `fact_unit_inventory_snapshot` | 1 căn × ngày snapshot | Giỏ hàng, bảng giá, chính sách bán; mock khi thiếu | `dim_date`, `dim_unit_master`, `dim_project_profile`, `dim_zone_master`, `dim_sales_channel` |
| 14 | `fact_sales_channel_performance` | 1 kênh × dự án × snapshot | CRM và tổng hợp giỏ hàng; mock khi thiếu | `dim_date`, `dim_sales_channel`, `dim_project_profile` |
| 15 | `dm_unit_friction_diagnostics` | 1 căn `AVAILABLE` × snapshot | Tính từ dimension/fact/benchmark theo semantic config | Inventory, funnel, macro, comps, unit |
| 16 | `unit_diagnostic_causes` | 1 nguyên nhân × căn chẩn đoán × snapshot | Quy tắc chẩn đoán deterministic và evidence | Mart chẩn đoán, `dim_unit_master`, `dim_date` |

## Quy tắc/kiểm tra liên bảng cần hiện thực ở DDL hoặc data quality

- **Khóa:** giữ đúng PK/UK/FK của từng cột bên dưới. PK ghép: inventory `(snapshot_date_key, unit_key)`, channel performance `(snapshot_date_key, channel_key, project_key)`, cause bridge `(diagnostic_id, cause_code)`.
- **Snapshot và thời gian:** `dim_date.date_key` là `YYYYMMDD`; `snapshot_manifest.semantic_version` phải khớp `semantic_config.semantic_version`. `AVAILABLE` có `sold_date IS NULL`; `SOLD` có `sold_date >= release_date`; DOM tính theo ngày chốt cho căn còn bán và theo ngày bán cho căn đã bán.
- **Giá và diện tích:** `net_price_vnd = asking_price_vnd × (1 − discount_pct/100) − concession_value_vnd`, `net_price_vnd <= asking_price_vnd`; đơn giá chia cho `dim_unit_master.net_area_m2`. `efficiency_ratio = net_area_m2 / gross_area_m2`.
- **Chẩn đoán:** chỉ gắn 8 nguyên nhân cốt lõi cho căn `AVAILABLE` có DOM > `overdue_threshold_days` (mặc định 90); `primary_cause_code` phải trùng cause rank 1 trong bridge; tổng `attribution_score` theo `diagnostic_id` = `1.000`.
- **Miền mã nguyên nhân:** `LEGAL_PERMIT_BARRIER`, `SEVERE_PHYSICAL_DEFECT`, `EXTREME_THERMAL_EXPOSURE`, `SECONDARY_ARBITRAGE`, `LUMP_SUM_TICKET_BARRIER`, `OVERPRICED_VS_PEER`, `LOW_SALES_INCENTIVE`, `DEEP_FUNNEL_DROP_OFF`. Cột bridge cho phép mã mở rộng theo đặc tả; tập 8 mã này là coverage bắt buộc của POC.
- **Giới hạn nguồn:** `recorded_resale_date` và `resale_price_per_m2_vnd` của comps đòi hỏi giao dịch xác thực; giá tin rao không được gắn nhãn giá giao dịch. Các giá trị chưa xác minh phải có provenance `mock` trong data pack.

### Ánh xạ FK trong warehouse

| Bảng nguồn | Cột → bảng đích |
| --- | --- |
| `dim_zone_master` | `project_key` → `dim_project_profile.project_key` |
| `dim_unit_master` | `project_key` → `dim_project_profile.project_key`; `zone_key` → `dim_zone_master.zone_key` |
| `fact_unit_inventory_snapshot` | `snapshot_date_key` → `dim_date.date_key`; `unit_key` → `dim_unit_master.unit_key`; `project_key` → `dim_project_profile.project_key`; `zone_key` → `dim_zone_master.zone_key`; `channel_key` → `dim_sales_channel.channel_key` |
| `fact_sales_funnel_daily` | `date_key` → `dim_date.date_key`; `unit_key` → `dim_unit_master.unit_key` |
| `fact_unit_price_history` | `unit_key` → `dim_unit_master.unit_key`; `effective_date_key` → `dim_date.date_key` |
| `fact_market_macro_monthly` | `date_key` → `dim_date.date_key` |
| `fact_sales_channel_performance` | `snapshot_date_key` → `dim_date.date_key`; `channel_key` → `dim_sales_channel.channel_key`; `project_key` → `dim_project_profile.project_key` |
| `dm_unit_friction_diagnostics` | `snapshot_date_key` → `dim_date.date_key`; `unit_key` → `dim_unit_master.unit_key` |
| `unit_diagnostic_causes` | `diagnostic_id` → `dm_unit_friction_diagnostics.diagnostic_id`; `unit_key` → `dim_unit_master.unit_key`; `snapshot_date_key` → `dim_date.date_key` |

**Quyết định cho bước DDL:** Các bảng có PK surrogate nhưng grain tự nhiên cần thêm kiểm tra duy nhất theo nghiệp vụ: `fact_sales_funnel_daily(date_key, unit_key)`, `fact_market_macro_monthly(date_key, market_id, segment)` và `dm_unit_friction_diagnostics(snapshot_date_key, unit_key)`. Đây là ràng buộc suy ra từ grain; chưa được đánh dấu UK trong đặc tả cột. `dim_project_profile.primary_infra_id` là tham chiếu logic, `unit_diagnostic_causes.evidence_artifact_id` liên kết sang backend; không tự ý tạo FK vật lý cho chúng. `snapshot_id` chỉ có trong `snapshot_manifest`, nên phía tích hợp phải giải mã snapshot sang `snapshot_date`/`snapshot_date_key` trước khi truy vấn fact/mart.

## Chi tiết cột theo đặc tả gốc

Các bảng dưới đây chép tên cột, kiểu dữ liệu, nullability, vai trò khóa và mô tả/ràng buộc từ đặc tả v3.1.0. Biểu thức toán học nhúng trong Word được diễn giải ở phần quy tắc phía trên; các đoạn công thức không trích xuất thành chữ được không xem là điều kiện DDL đã chốt.

### 1. `snapshot_manifest`

**Grain:** Đúng 1 dòng cho một phiên chốt sổ dữ liệu.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| snapshot_id | VARCHAR(64) | Không | PK | Mã định danh snapshot bất biến (Ví dụ: 'SNAP-20260630-01'). |
| dataset_id | VARCHAR(64) | Không | - | Tên định danh kho dữ liệu ('vdagent_dw_re'). |
| dataset_version | VARCHAR(16) | Không | - | Phiên bản dữ liệu tuân thủ SemVer 2.0.0 (Ví dụ: '3.1.0'). |
| semantic_version | VARCHAR(16) | Không | - | Khớp tuyệt đối với semantic_config.semantic_version. |
| snapshot_date | DATE | Không | - | Ngày chốt dữ liệu. Mọi phép tính DOM bắt buộc căn cứ mốc này. |
| timezone | VARCHAR(32) | Không | - | Múi giờ chuẩn: 'Asia/Ho_Chi_Minh'. |
| currency | VARCHAR(8) | Không | - | Đơn vị tiền tệ hạch toán chuẩn: 'VND'. |
| price_basis | VARCHAR(32) | Không | - | Cơ sở giá: 'ASKING_EXCL_VAT_EXCL_MAINT' (chưa VAT và KPBT). |
| area_basis | VARCHAR(32) | Không | - | Cơ sở đo chuẩn: 'NET_INTERNAL_M2' (Diện tích thông thủy). |
| source_system | VARCHAR(64) | Không | - | Nguồn dữ liệu: 'ENTERPRISE_DW_RE'. |

### 2. `semantic_config`

**Grain:** 1 dòng / 1 tham số cấu hình quy tắc phân tích.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| config_key | VARCHAR(64) | Không | PK | Tên tham số duy nhất (Ví dụ: 'overdue_threshold_days'). |
| config_value | VARCHAR(256) | Không | - | Giá trị cấu hình dạng chuỗi (Ví dụ: '90', '0.10'). |
| value_type | VARCHAR(16) | Không | - | Kiểu ép dữ liệu đích: 'INTEGER', 'DECIMAL', 'BOOLEAN', 'STRING'. |
| semantic_version | VARCHAR(16) | Không | - | Phiên bản cấu hình áp dụng. |
| approval_status | VARCHAR(16) | Không | - | Trạng thái phê duyệt: 'APPROVED', 'PENDING'. |
| description | TEXT | Có | - | Diễn giải chi tiết ý nghĩa nghiệp vụ và phạm vi áp dụng. |

### 3. `dim_date`

**Grain:** 1 dòng / 1 ngày theo lịch chuẩn Gregorian.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| date_key | INTEGER | Không | PK | Khóa thay thế định dạng số nguyên YYYYMMDD (Ví dụ: 20260630). |
| full_date | DATE | Không | UK | Ngày đầy đủ theo định dạng chuẩn ISO-8601. |
| year | SMALLINT | Không | - | Năm dương lịch (Ví dụ: 2026). |
| quarter | SMALLINT | Không | - | Quý trong năm (1, 2, 3, 4). |
| month | SMALLINT | Không | - | Tháng trong năm (1 đến 12). |
| day_of_month | SMALLINT | Không | - | Ngày trong tháng (1 đến 31). |
| is_weekend | BOOLEAN | Không | - | Cờ ngày nghỉ cuối tuần (Thứ 7, Chủ Nhật). |
| fiscal_quarter | VARCHAR(8) | Không | - | Chu kỳ quý tài chính (Ví dụ: '2026-Q2'). |

### 4. `dim_project_profile`

**Grain:** 1 dòng / 1 dự án bất động sản.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| project_key | INTEGER | Không | PK | Khóa thay thế tự tăng của dự án (Surrogate Key). |
| project_id | VARCHAR(32) | Không | UK | Mã tự nhiên định danh dự án (Ví dụ: 'PRJ-X'). |
| project_name | VARCHAR(128) | Không | - | Tên thương mại chính thức của dự án. |
| market_id | VARCHAR(32) | Không | - | Phân vùng thị trường địa lý (Ví dụ: 'MKT-EAST-HCM'). |
| market_name | VARCHAR(64) | Không | - | Tên khu vực thị trường địa lý. |
| province_city | VARCHAR(64) | Không | - | Tỉnh hoặc Thành phố trực thuộc Trung ương. |
| district | VARCHAR(64) | Không | - | Quận, Huyện hoặc Thành phố thuộc tỉnh. |
| developer_name | VARCHAR(128) | Không | - | Tên chủ đầu tư hoặc đơn vị phát triển. |
| developer_tier | VARCHAR(16) | Không | - | Uy tín CĐT: 'TIER_1', 'TIER_2', 'TIER_3'. |
| developer_origin | VARCHAR(16) | Không | - | Xuất xứ: 'DOMESTIC', 'FOREIGN_FDI'. |
| segment | VARCHAR(32) | Không | - | Phân khúc: 'AFFORDABLE', 'MID', 'MID_HIGH', 'LUXURY'. |
| construction_status | VARCHAR(32) | Không | - | Hiện trạng: 'FOUNDATION', 'SUPERSTRUCTURE', 'TOPPED_OUT', 'HANDED_OVER'. |
| construction_progress_pct | DECIMAL(5,2) | Không | - | Tiến độ thi công thực tế lũy kế (%). |
| is_sales_permit_issued | BOOLEAN | Không | - | Cờ có văn bản đủ điều kiện mở bán của Sở Xây dựng (Luật 2023). |
| is_bank_guarantee_issued | BOOLEAN | Không | - | Cờ có chứng thư bảo lãnh bàn giao nhà của Ngân hàng thương mại. |
| max_foreign_quota_exceeded | BOOLEAN | Không | - | Cờ đã hết trần   bán cho người nước ngoài. |
| primary_infra_id | VARCHAR(32) | Có | - | Mã hạ tầng giao thông kết nối trực tiếp. |
| distance_to_primary_infra_m | INTEGER | Có | - | Khoảng cách thực tế đến hạ tầng giao thông trọng điểm (mét). |
| partner_bank_name | VARCHAR(64) | Có | - | Ngân hàng bảo lãnh và tài trợ gói vay ưu đãi chính. |
| expected_handover_date | DATE | Có | - | Ngày dự kiến bàn giao căn hộ cho cư dân. |

### 5. `dim_zone_master`

**Grain:** 1 dòng / 1 phân khu địa lý hoặc 1 tòa tháp thuộc dự án.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| zone_key | INTEGER | Không | PK | Khóa thay thế của phân khu / tòa tháp. |
| zone_id | VARCHAR(32) | Không | UK | Mã định danh tòa tháp (Ví dụ: 'ZN-LANDMARK-01'). |
| project_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_project_profile. |
| zone_name | VARCHAR(64) | Không | - | Tên thương mại của tòa nhà (Ví dụ: 'Tòa Aqua 1'). |
| zone_type | VARCHAR(32) | Không | - | Phân loại: 'HIGH_RISE_TOWER', 'LOW_RISE_VILLA', 'SHOPHOUSE'. |
| total_floors | SMALLINT | Có | - | Tổng số tầng nổi của tòa nhà. |
| basement_floors | SMALLINT | Có | - | Số lượng tầng hầm đỗ xe. |
| units_per_floor | SMALLINT | Không | - | Mật độ căn hộ trên một mặt sàn tầng điển hình. |
| passenger_elevators | SMALLINT | Không | - | Số lượng thang máy chở khách hoạt động. |
| elevator_ratio | DECIMAL(4,1) | Không | - | Tỷ số căn/thang máy = units_per_floor / passenger_elevators. |
| handover_standard | VARCHAR(32) | Không | - | Tiêu chuẩn bàn giao: 'BARE_SHELL', 'BASIC_FINISH', 'FULLY_FURNISHED'. |

### 6. `dim_unit_master`

**Grain:** 1 dòng / 1 căn hộ vật lý độc lập trong giỏ hàng.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| unit_key | BIGINT | Không | PK | Khóa thay thế của căn hộ (Surrogate Key). |
| unit_id | VARCHAR(32) | Không | UK | Mã kỹ thuật duy nhất của căn hộ (Ví dụ: 'U011'). |
| unit_code | VARCHAR(32) | Không | - | Mã số thương mại trên mặt bằng (Ví dụ: 'A-05.03'). |
| project_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_project_profile. |
| zone_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_zone_master. |
| unit_type | VARCHAR(16) | Không | - | Loại căn: 'STUDIO', '1PN', '2PN', '3PN', '4PN', 'PENTHOUSE'. |
| bedroom_count | SMALLINT | Không | - | Số lượng phòng ngủ thực tế. |
| bathroom_count | SMALLINT | Không | - | Số lượng phòng vệ sinh. |
| net_area_m2 | DECIMAL(8,2) | Không | - | Diện tích thông thủy ( ),  . Căn cứ tính đơn giá chuẩn. |
| gross_area_m2 | DECIMAL(8,2) | Không | - | Diện tích tim tường ( ),  . |
| floor_number | SMALLINT | Không | - | Vị trí tầng thực tế của căn hộ ( ). |
| floor_band | VARCHAR(16) | Không | - | Nhóm tầng: 'LOW' (1-5), 'MID' (6-20), 'HIGH' (21-35), 'TOP' ( ). |
| balcony_orientation | VARCHAR(4) | Không | - | Hướng ban công chính: 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'. |
| door_orientation | VARCHAR(4) | Có | - | Hướng cửa chính mở vào căn hộ. |
| view_primary_type | VARCHAR(32) | Không | - | Tầm nhìn chính: 'RIVER', 'PARK', 'POOL', 'CITY_OPEN', 'OBSTRUCTED'. |
| is_corner_unit | BOOLEAN | Không | - | Cờ căn góc (sở hữu từ 2 mặt thoáng trở lên). |
| efficiency_ratio | DECIMAL(4,3) | Không | - | Tỷ lệ diện tích hữu dụng = net_area_m2 / gross_area_m2. |
| distance_to_trash_room_m | DECIMAL(4,1) | Có | - | Cự ly từ cửa căn đến phòng rác tầng (mét). |
| is_adjacent_elevator | BOOLEAN | Không | - | Cờ tiếp giáp vách thang máy hoặc phòng kỹ thuật điện. |
| dark_bedroom_count | SMALLINT | Không | - | Số phòng ngủ âm, thiếu sáng (không có cửa sổ ngoài trời). |
| west_facing_exposure_pct | DECIMAL(4,2) | Không | - | Tỷ lệ mặt ngoài tiếp xúc hướng nắng Tây/Tây Nam. |
| view_obstruction_distance_m | DECIMAL(5,1) | Có | - | Khoảng cách tới tòa nhà đối diện gần nhất (mét). |
| taboo_view_type | VARCHAR(32) | Có | - | Tầm nhìn phong thủy xấu: 'CEMETERY', 'WASTE_STATION', 'TEMPLE', 'NONE'. |
| is_taboo_floor | BOOLEAN | Không | - | Cờ tầng kiêng kỵ tâm lý Á Đông (Tầng 4, 7, 13, 14). |
| ext_attributes | JSONB | Có | - | Trường JSONB mở rộng các thuộc tính phát sinh mà không cần sửa bảng. |

### 7. `dim_sales_channel`

**Grain:** 1 dòng / 1 đơn vị hoặc sàn đại lý phân phối.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| channel_key | INTEGER | Không | PK | Khóa thay thế của kênh phân phối. |
| channel_id | VARCHAR(32) | Không | UK | Mã tự nhiên của đại lý (Ví dụ: 'AGENCY-CENLAND'). |
| channel_name | VARCHAR(128) | Không | - | Tên thương mại của sàn đại lý phân phối. |
| channel_tier | VARCHAR(16) | Không | - | Cấp sàn: 'TIER_1_EXCLUSIVE', 'TIER_2_GENERAL', 'INHOUSE'. |
| active_brokers_count | INTEGER | Có | - | Số lượng môi giới đang tham gia bán giỏ hàng. |

### 8. `dim_infrastructure_assets`

**Grain:** 1 dòng / 1 công trình hạ tầng kỹ thuật trọng điểm ngoại khu.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| infra_key | INTEGER | Không | PK | Khóa thay thế của tài sản hạ tầng. |
| infra_id | VARCHAR(32) | Không | UK | Mã định danh công trình hạ tầng (Ví dụ: 'INF-METRO-01'). |
| infra_name | VARCHAR(128) | Không | - | Tên công trình (Ví dụ: 'Tuyến Metro số 1 Bến Thành - Suối Tiên'). |
| infra_type | VARCHAR(32) | Không | - | Loại hình: 'URBAN_METRO', 'RING_ROAD', 'EXPRESSWAY', 'BRIDGE', 'AIRPORT'. |
| lifecycle_stage | VARCHAR(32) | Không | - | Giai đoạn: 'PLANNING_APPROVED', 'UNDER_CONSTRUCTION', 'COMMERCIAL_OPERATION'. |
| construction_progress_pct | DECIMAL(5,2) | Có | - | Tiến độ xây lắp thực tế lũy kế (%). |
| original_completion_year | SMALLINT | Có | - | Năm hoàn thành dự kiến ban đầu theo quy hoạch. |
| revised_completion_year | SMALLINT | Có | - | Năm hoàn thành điều chỉnh thực tế (nếu trễ hạn). |

### 9. `fact_unit_inventory_snapshot`

**Grain:** Đúng 1 dòng / 1 căn hộ vật lý / 1 ngày chốt snapshot (unit_key  snapshot_date_key).

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| snapshot_date_key | INTEGER | Không | PK, FK | Khóa ngày chốt dữ liệu (YYYYMMDD), trỏ sang dim_date. |
| unit_key | BIGINT | Không | PK, FK | Khóa thay thế căn hộ vật lý, trỏ sang dim_unit_master. |
| project_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_project_profile. |
| zone_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_zone_master. |
| channel_key | INTEGER | Không | FK | Khóa ngoại trỏ sang dim_sales_channel. |
| launch_batch_id | VARCHAR(32) | Không | - | Mã đợt mở bán (Cohort Batch ID). |
| release_date | DATE | Không | - | Ngày chính thức mở bán căn hộ ra thị trường. |
| inventory_status | VARCHAR(16) | Không | - | Trạng thái chốt: 'AVAILABLE', 'BOOKED', 'SOLD'. |
| sold_date | DATE | Có | - | Ngày ký HĐMB (bắt buộc NULL nếu chưa bán). |
| unsold_days_dom | INTEGER | Không | - | Số ngày tồn lũy kế DOM = snapshot_date - release_date. |
| is_overdue_flag | BOOLEAN | Không | - | Cờ quá hạn bán: TRUE khi còn 'AVAILABLE' và DOM   ngày. |
| asking_price_vnd | BIGINT | Không | - | Giá niêm yết CĐT (chưa VAT và KPBT). |
| discount_pct | DECIMAL(5,2) | Không | - | Tổng tỷ lệ chiết khấu thương mại đang áp dụng (%). |
| concession_value_vnd | BIGINT | Không | - | Tổng quà tặng, nội thất quy đổi ra tiền (VND). |
| net_price_vnd | BIGINT | Không | - | Giá ròng =  . |
| asking_price_per_m2 | BIGINT | Không | - | Đơn giá chào/m² thông thủy = asking_price_vnd / net_area_m2. |
| net_price_per_m2 | BIGINT | Không | - | Đơn giá ròng/m² thông thủy = net_price_vnd / net_area_m2. |
| subsidy_duration_mo | SMALLINT | Không | - | Số tháng CĐT hỗ trợ lãi suất vay 0%. |
| principal_grace_mo | SMALLINT | Không | - | Số tháng ngân hàng ân hạn nợ gốc. |
| base_commission_pct | DECIMAL(4,2) | Không | - | Tỷ lệ hoa hồng môi giới cơ bản áp dụng cho căn hộ (%). |
| spiff_bonus_vnd | BIGINT | Có | - | Tiền thưởng nóng bằng tiền mặt cho môi giới chốt cọc. |
| is_exclusive_lock | BOOLEAN | Không | - | Cờ căn hộ bị sàn môi giới khóa giữ độc quyền. |

### 10. `fact_sales_funnel_daily`

**Grain:** 1 dòng / 1 căn hộ / 1 ngày phát sinh tương tác trong phễu bán hàng.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| funnel_event_id | BIGINT | Không | PK | Khóa tự tăng của sự kiện tương tác phễu. |
| date_key | INTEGER | Không | FK | Ngày phát sinh tương tác, trỏ sang dim_date. |
| unit_key | BIGINT | Không | FK | Khóa ngoại trỏ sang dim_unit_master. |
| web_listing_views | INTEGER | Không | - | Số lượt xem thông tin chi tiết căn hộ trên web/app. |
| inquiry_leads_count | SMALLINT | Không | - | Số lượng khách hàng để lại thông tin tư vấn. |
| site_visits_count | SMALLINT | Không | - | Số lượt môi giới dẫn khách tới xem thực địa. |
| booking_reservations | SMALLINT | Không | - | Số lượt khách nộp tiền đặt cọc giữ chỗ thiện chí (cọc 5%). |
| booking_cancellations | SMALLINT | Không | - | Số lượt khách quyết định rút cọc, từ chối ký HĐMB. |
| cancellation_reason | VARCHAR(64) | Có | - | Lý do rút cọc: 'PRICE_TOO_HIGH', 'DEFECT_FOUND', 'LOAN_REJECTED'. |

### 11. `fact_unit_price_history`

**Grain:** 1 dòng / 1 sự kiện thay đổi giá niêm yết hoặc chính sách chiết khấu của căn hộ.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| price_event_id | BIGINT | Không | PK | Mã định danh sự kiện thay đổi biểu giá. |
| unit_key | BIGINT | Không | FK | Khóa ngoại trỏ sang dim_unit_master. |
| effective_date_key | INTEGER | Không | FK | Ngày biểu giá mới bắt đầu có hiệu lực áp dụng. |
| old_asking_price_vnd | BIGINT | Không | - | Giá chào niêm yết cũ trước khi điều chỉnh. |
| new_asking_price_vnd | BIGINT | Không | - | Giá chào niêm yết mới sau khi điều chỉnh. |
| price_change_pct | DECIMAL(5,2) | Không | - | Tỷ lệ biến động giá = (new - old) / old * 100. |
| change_reason | VARCHAR(64) | Có | - | Lý do điều chỉnh: 'STIMULATE_SLOW_MOVING', 'MARKET_RALLY', 'CAMPAIGN'. |

### 12. `dim_secondary_market_comps`

**Grain:** 1 dòng / 1 giao dịch bán lại thứ cấp được xác thực tại cùng tiểu khu.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| comp_id | VARCHAR(32) | Không | PK | Mã định danh bản ghi đối chiếu thứ cấp. |
| project_id | VARCHAR(32) | Không | - | Mã dự án hoặc khu căn hộ lân cận tương đồng. |
| unit_type | VARCHAR(16) | Không | - | Phân loại căn hộ: '1PN', '2PN', '3PN'. |
| floor_band | VARCHAR(16) | Không | - | Nhóm tầng của căn đối chiếu. |
| balcony_orientation | VARCHAR(4) | Không | - | Hướng ban công của căn đối chiếu. |
| recorded_resale_date | DATE | Không | - | Ngày ghi nhận giao dịch bán lại thành công. |
| resale_price_per_m2_vnd | BIGINT | Không | - | Đơn giá giao dịch thực tế trên m² thông thủy (VND). |
| pink_book_status | VARCHAR(32) | Không | - | Tình trạng pháp lý: 'PINK_BOOK_AVAILABLE', 'SPA_ASSIGNMENT'. |

### 13. `fact_market_macro_monthly`

**Grain:** 1 dòng / 1 phân vùng thị trường / 1 phân khúc / 1 tháng theo dõi.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| macro_record_id | VARCHAR(32) | Không | PK | Mã định danh bản ghi vĩ mô. |
| date_key | INTEGER | Không | FK | Khóa ngày cuối cùng của tháng theo dõi, trỏ sang dim_date. |
| market_id | VARCHAR(32) | Không | - | Mã phân vùng thị trường địa lý. |
| segment | VARCHAR(32) | Không | - | Phân khúc sản phẩm khảo sát. |
| floating_mortgage_rate_pct | DECIMAL(4,2) | Không | - | Lãi suất vay thả nổi bình quân thị trường (%/năm). |
| months_of_inventory_moi | DECIMAL(4,1) | Có | - | Số tháng tồn kho cần thiết để tiêu thụ hết nguồn cung. |
| absorption_rate_pct | DECIMAL(5,2) | Không | - | Tỷ lệ hấp thụ nguồn cung sơ cấp trên toàn địa bàn (%). |
| median_household_income_vnd | BIGINT | Không | - | Thu nhập trung vị năm của hộ gia đình địa phương (VND/năm). |
| macro_price_to_income_ratio | DECIMAL(4,1) | Có | - | Tỷ số Giá nhà / Thu nhập (PIR) trung bình toàn địa bàn. |

### 14. `fact_sales_channel_performance`

**Grain:** 1 dòng / 1 kênh phân phối / 1 dự án / 1 chu kỳ đóng sổ snapshot.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| snapshot_date_key | INTEGER | Không | PK, FK | Khóa ngày chốt dữ liệu, trỏ sang dim_date. |
| channel_key | INTEGER | Không | PK, FK | Khóa đại lý phân phối, trỏ sang dim_sales_channel. |
| project_key | INTEGER | Không | PK, FK | Khóa dự án, trỏ sang dim_project_profile. |
| assigned_units_count | INTEGER | Không | - | Tổng số căn hộ giao cho sàn phân phối độc quyền. |
| sold_units_count | INTEGER | Không | - | Số căn hộ sàn đã giao dịch thành công ký HĐMB. |
| absorption_rate_pct | DECIMAL(5,2) | Không | - | Tỷ lệ hấp thụ riêng của sàn = (sold / assigned) * 100. |
| avg_days_to_sell | INTEGER | Có | - | Số ngày bán trung bình của một căn hộ qua sàn này. |
| locked_inventory_over_90d | INTEGER | Không | - | Số căn tồn kho quá 90 ngày đang bị sàn này khóa giữ. |

### 15. `dm_unit_friction_diagnostics`

**Grain:** 1 dòng / 1 căn hộ tồn kho (inventory_status = 'AVAILABLE') tại ngày snapshot.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| diagnostic_id | VARCHAR(64) | Không | PK | Mã chẩn đoán duy nhất (Ví dụ: 'DIAG-20260630-U011'). |
| snapshot_date_key | INTEGER | Không | FK | Ngày chốt dữ liệu phân tích chẩn đoán. |
| unit_key | BIGINT | Không | FK | Khóa căn hộ tồn kho được chẩn đoán. |
| unit_code | VARCHAR(32) | Không | - | Mã số căn hộ thương mại trực quan (Ví dụ: 'A-05.03'). |
| project_name | VARCHAR(128) | Không | - | Tên dự án (phẳng hóa phục vụ prompt LLM). |
| zone_name | VARCHAR(64) | Không | - | Tên tòa tháp / phân khu. |
| unsold_days_dom | INTEGER | Không | - | Số ngày mở bán chưa có giao dịch thành công. |
| price_spread_vs_peer_pct | DECIMAL(5,2) | Có | - | Độ chênh lệch % đơn giá/m² so với trung vị Peer Group chuẩn hóa. |
| ticket_size_vs_income_ratio | DECIMAL(4,1) | Có | - | Tỷ số Tổng giá căn hộ / Thu nhập hộ gia đình năm tại địa bàn. |
| physical_defect_penalty | SMALLINT | Không | - | Tổng điểm phạt khuyết tật cấu trúc vật lý (thang 0 - 100). |
| thermal_view_penalty | SMALLINT | Không | - | Tổng điểm phạt bức xạ nhiệt & tầm nhìn kiêng kỵ (thang 0 - 100). |
| secondary_price_gap_pct | DECIMAL(5,2) | Có | - | Độ chênh lệch % giá sơ cấp so với trung vị căn thứ cấp tương đương. |
| funnel_dropoff_rate_pct | DECIMAL(5,2) | Có | - | Tỷ lệ khách vào cọc giữ chỗ nhưng sau đó rút cọc hủy mua (%). |
| primary_cause_code | VARCHAR(32) | Không | - | Mã nguyên nhân cốt lõi số 1 (xếp hạng cao nhất). |
| recommended_action | VARCHAR(64) | Không | - | Khuyến nghị hành động có bằng chứng dành cho cấp quản lý. |

### 16. `unit_diagnostic_causes`

**Grain:** 1 dòng / 1 nguyên nhân tác động lên 1 căn hộ chẩn đoán tại kỳ snapshot.

| Cột | Kiểu dữ liệu | Null? | Khóa | Ý nghĩa / enum / ràng buộc trong đặc tả |
| --- | --- | --- | --- | --- |
| diagnostic_id | VARCHAR(64) | Không | PK, FK | Trỏ trực tiếp sang dm_unit_friction_diagnostics.diagnostic_id. |
| cause_code | VARCHAR(32) | Không | PK | 1 trong 8 mã nguyên nhân cốt lõi (hoặc mã mở rộng). |
| unit_key | BIGINT | Không | FK | Khóa ngoại trỏ sang dim_unit_master. |
| snapshot_date_key | INTEGER | Không | FK | Ngày chốt dữ liệu, trỏ sang dim_date. |
| severity_rank | SMALLINT | Không | - | Thứ hạng ảnh hưởng: 1 (nguyên nhân chính), 2, 3 (nguyên nhân phụ). |
| attribution_score | DECIMAL(4,3) | Không | - | Tỷ trọng đóng góp nguyên nhân (tổng điểm các rank của 1 căn = 1.000). |
| evidence_artifact_id | VARCHAR(64) | Có | - | Khóa liên kết logic sang shared_artifacts chứa chứng cứ tính toán. |
