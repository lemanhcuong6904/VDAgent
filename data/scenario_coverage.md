# Scenario coverage — snapshot 30/06/2026

Chi tiết 316 căn chẩn đoán trong pack 3.000 căn và mã nguyên nhân mong đợi nằm trong [`mock/vhsc_20260630/expected_scenarios.json`](mock/vhsc_20260630/expected_scenarios.json). Các ví dụ dưới đây đều là **mock**. Trường pháp lý của dự án Vinhomes Smart City thật không được suy ra từ bộ dữ liệu này.

| Mã nguyên nhân chính | Số căn | Ví dụ `unit_id` | Điều kiện và bằng chứng kiểm tra |
| --- | ---: | --- | --- |
| `LEGAL_PERMIT_BARRIER` | 16 | `SMC-U02985` | Chỉ ở phase kiểm thử **hư cấu** `MOCK-LGL-01`; `ext_attributes.phase_sales_permit_issued=false`, không suy từ trạng thái pháp lý của dự án thật |
| `SEVERE_PHYSICAL_DEFECT` | 43 | `SMC-U00001` | Khoảng cách tới phòng rác 1,5 m; `physical_defect_penalty >= 25`; chiết khấu 0 |
| `EXTREME_THERMAL_EXPOSURE` | 43 | `SMC-U00137` | Hướng W, tỷ lệ phơi nắng 0,80; điểm nhiệt >=40; hỗ trợ lãi suất 12 tháng |
| `SECONDARY_ARBITRAGE` | 43 | `SMC-U00046` | `secondary_price_gap_pct > 15`; đối sánh mock có ngày trong 90 ngày |
| `LUMP_SUM_TICKET_BARRIER` | 43 | `SMC-U00034` | Căn 3PN diện tích 94 m²; PIR >25; đơn giá ngang peer |
| `OVERPRICED_VS_PEER` | 43 | `SMC-U00017` | `price_spread_vs_peer_pct > 8`; không có điểm phạt vật lý/nhiệt |
| `LOW_SALES_INCENTIVE` | 43 | `SMC-U00023` | Hoa hồng 1,2%, thưởng 0, ít lượt xem |
| `DEEP_FUNNEL_DROP_OFF` | 42 | `SMC-U00057` | 300 lượt xem, 30 lượt xem thực địa, 10 cọc và 8 hủy; drop-off 80% |

Mỗi căn trong bảng chẩn đoán là `AVAILABLE` và DOM >90. Bridge có nguyên nhân phụ khi cùng căn thỏa nhiều tín hiệu; `severity_rank=1` khớp nguyên nhân chính và tổng `attribution_score=1.000`. Bộ đối chứng ở [`negative_controls.json`](mock/vhsc_20260630/negative_controls.json): căn `SOLD`, căn `BOOKED`, căn `AVAILABLE` DOM đúng 90 (đều không được chẩn đoán), và căn DOM 91 (phải được chẩn đoán). Kiểm tra bằng [`verify_vhsc_mock.sql`](verify_vhsc_mock.sql).

**TC-13/15 tạm giả định:** [`tc_assumptions.json`](mock/vhsc_20260630/tc_assumptions.json) chọn TC-13 = rào cản giấy phép ở phase hư cấu (`SMC-U03000`), TC-15 = rơi rụng sâu tại phễu bán (`SMC-U02831`). Đây là hai fixture có ground truth và kiểm tra tự động, **chưa phải bằng chứng đáp ứng Scenario Coverage Matrix chính thức**; phải đối chiếu lại khi BA cung cấp đặc tả.
