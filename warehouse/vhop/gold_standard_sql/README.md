<!-- gold_standard_sql/README.md -->
# Gold Standard SQL — Vinhomes Ocean Pack

Tập truy vấn chuẩn dùng để đối chiếu kết quả chẩn đoán trong
`dm_unit_friction_diagnostics` với dữ liệu nguồn. Mỗi file bắt đầu bằng comment
mô tả metric, công thức và khoá `semantic_config` liên quan.

| File | Metric | Nguồn |
|---|---|---|
| `01_peer_spread.sql` | `price_spread_vs_peer_pct` | fact_unit_inventory_snapshot + dim_unit_master |
| `02_physical_defect_penalty.sql` | `physical_defect_penalty` | dim_unit_master |
| `03_thermal_view_penalty.sql` | `thermal_view_penalty` | dim_unit_master |
| `04_funnel_dropoff.sql` | `funnel_dropoff_rate_pct` | fact_sales_funnel_daily |
| `05_ticket_income_ratio.sql` | `ticket_size_vs_income_ratio` | fact_unit_inventory_snapshot + fact_market_macro_monthly |
| `06_secondary_price_gap.sql` | `secondary_price_gap_pct` | dim_secondary_market_comps + fact_unit_inventory_snapshot |
| `07_cause_matrix.sql` | tập nguyên nhân + `severity_rank` (8 vị ngữ kích hoạt) | dm_unit_friction_diagnostics + dim_project_profile + fact_unit_inventory_snapshot + fact_sales_funnel_daily |

Các truy vấn này được `tests/reconciliation/` nạp trực tiếp, không viết lại SQL.
Ngưỡng lấy từ `semantic_config`. Các metric `SMALLINT` (`02`, `03`) được so khớp
tuyệt đối; các metric phần trăm (`01`, `04`, `05`, `06`) được so khớp với sai số
tối đa 0.01; `net_price_per_m2`/`asking_price_per_m2` (BigInt) được so khớp tuyệt đối.
`07` tính lại tập nguyên nhân + `severity_rank` (top-3 theo thứ tự if của engine)
từ nguồn rồi đối chiếu bridge bằng FULL OUTER JOIN — nguyên nhân thừa/thiếu/sai
hạng đều lộ ra.

## Giới hạn của đối chiếu BigInt VND/m²

Test `test_bigint_price_per_m2_matches` tính lại `round(price_vnd / net_area_m2)`
bằng chính Postgres. Vì `net_area_m2` lưu tối đa 2 chữ số thập phân (chính xác
trong `DECIMAL(8,2)`), python `round()` và SQL `round()` chỉ khác nhau đúng ở các
giá trị `.5` (Python làm tròn banker's, SQL làm tròn xa 0). Bộ dữ liệu hiện tại
không có trường hợp `.5` nào; nếu seed/config đổi tạo ra `.5`, test sẽ lộ ra và
cần đối chiếu bằng một oracle độc lập thay vì `round()` của Postgres.

## Giới hạn của `01_peer_spread.sql`

`01_peer_spread.sql` mô phỏng trung thực thuật toán `select_peers` của engine
(cùng dự án/batch/loại căn/nhóm hướng, dung sai diện tích ±`peer_area_tolerance_pct`,
cùng dải tầng rồi mở rộng lần lượt sang dải tầng lân cận cho tới khi đủ
`min_peer_count`, trung vị theo quy ước số nguyên của engine).

Vì là bản chép lại đúng hành vi hiện tại, nó **đóng băng/găm (pin) hành vi engine**
chứ không phải một oracle độc lập: nó bắt được drift do loader (sai kiểu, mất dòng,
lệch dữ liệu nguồn) và drift do làm tròn, nhưng **không thể tự phát hiện lỗi trong
chính thuật toán peer/median** — nếu engine sai một cách nhất quán thì cả hai vế
cùng sai và test vẫn xanh. Việc kiểm chứng độc lập thuật toán cần một nguồn đối
chiếu khác (tài liệu spec hoặc oracle viết độc lập), không nằm trong phạm vi file này.

