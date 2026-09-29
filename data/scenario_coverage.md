# Scenario coverage — snapshot 30/06/2026

Chi tiết 136 căn chẩn đoán và mã nguyên nhân mong đợi nằm trong [`mock/vhsc_20260630/expected_scenarios.json`](mock/vhsc_20260630/expected_scenarios.json). Các ví dụ dưới đây đều là **mock**. Trường pháp lý của dự án Vinhomes Smart City thật không được suy ra từ bộ dữ liệu này.

| Mã nguyên nhân chính | Số căn | Ví dụ `unit_id` | Điều kiện và bằng chứng kiểm tra |
| --- | ---: | --- | --- |
| `LEGAL_PERMIT_BARRIER` | 16 | `VHSC-U-01201` | Chỉ ở phân kỳ hư cấu `PRJ-VHSC-LEGAL-MOCK`; cờ giấy phép/bảo lãnh = false |
| `SEVERE_PHYSICAL_DEFECT` | 18 | `VHSC-U-00042` | Khoảng cách tới phòng rác 1,5 m; `physical_defect_penalty >= 25`; chiết khấu 0 |
| `EXTREME_THERMAL_EXPOSURE` | 17 | `VHSC-U-00040` | Hướng W, tỷ lệ phơi nắng 0,80; điểm nhiệt >=40; hỗ trợ lãi suất 12 tháng |
| `SECONDARY_ARBITRAGE` | 17 | `VHSC-U-00013` | `secondary_price_gap_pct > 15`; đối sánh mock có ngày trong 90 ngày |
| `LUMP_SUM_TICKET_BARRIER` | 17 | `VHSC-U-00200` | Căn 3PN diện tích 94 m²; PIR >25; đơn giá ngang peer |
| `OVERPRICED_VS_PEER` | 17 | `VHSC-U-00078` | `price_spread_vs_peer_pct > 8`; không có điểm phạt vật lý/nhiệt |
| `LOW_SALES_INCENTIVE` | 17 | `VHSC-U-00032` | Hoa hồng 1,2%, thưởng 0, ít lượt xem |
| `DEEP_FUNNEL_DROP_OFF` | 17 | `VHSC-U-00003` | 300 lượt xem, 30 lượt xem thực địa, 10 cọc và 8 hủy; drop-off 80% |

Mỗi căn trong bảng chẩn đoán là `AVAILABLE` và DOM >90. Bridge có nguyên nhân phụ khi cùng căn thỏa nhiều tín hiệu; `severity_rank=1` khớp nguyên nhân chính và tổng `attribution_score=1.000`. Bộ đối chứng ở [`negative_controls.json`](mock/vhsc_20260630/negative_controls.json): căn `SOLD`, căn `BOOKED`, căn `AVAILABLE` DOM đúng 90 (đều không được chẩn đoán), và căn DOM 91 (phải được chẩn đoán). Kiểm tra bằng [`verify_vhsc_mock.sql`](verify_vhsc_mock.sql).
