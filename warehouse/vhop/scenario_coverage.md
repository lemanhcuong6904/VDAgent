# Ma trận bao phủ kịch bản — Vinhomes Ocean Park

- Snapshot: `SNAP-20260630-01` (2026-06-30)
- Semantic version: `3.1.0`
- Tổng số căn: 3000
- Số chẩn đoán (AVAILABLE & DOM>90): 1114

| # | Mã nguyên nhân | Điều kiện kích hoạt | Số căn (primary) | unit_code mẫu |
|---|---|---|---|---|
| 1 | `SEVERE_PHYSICAL_DEFECT` | physical_defect_penalty>=25 AND price_spread>=0 | 147 | OCP-U00001, OCP-U00002, OCP-U00003, OCP-U00008, OCP-U00010 |
| 2 | `EXTREME_THERMAL_EXPOSURE` | thermal_view_penalty>=40 AND subsidy<24 | 367 | OCP-U00003, OCP-U00009, OCP-U00017, OCP-U00018, OCP-U00023 |
| 3 | `SECONDARY_ARBITRAGE` | secondary_price_gap_pct>=10 AND comp trong 90 ngày | 207 | OCP-U00001, OCP-U00008, OCP-U00011, OCP-U00018, OCP-U00023 |
| 4 | `LUMP_SUM_TICKET_BARRIER` | ticket_ratio>=15 AND \|price_spread\|<=10 | 10 | OCP-U01121, OCP-U01122, OCP-U01123, OCP-U01124, OCP-U01126 |
| 5 | `OVERPRICED_VS_PEER` | price_spread>=10 AND defect<=24 | 49 | OCP-U00040, OCP-U00062, OCP-U00065, OCP-U00101, OCP-U00103 |
| 6 | `LOW_SALES_INCENTIVE` | commission<=1.5 AND spiff rỗng AND views<50 | 112 | OCP-U00032, OCP-U00043, OCP-U00050, OCP-U00063, OCP-U00077 |
| 7 | `DEEP_FUNNEL_DROP_OFF` | dropoff>=60 AND bookings>=5 AND views>=300 AND visits>=10 | 222 | OCP-U00001, OCP-U00002, OCP-U00003, OCP-U00004, OCP-U00005 |

## Ghi chú
- Ngưỡng lấy từ `semantic_config`; các giá trị `PENDING` cần xác nhận.
- `attribution_score` của mỗi `diagnostic_id` luôn có tổng = 1.000.
- `unit_code` mẫu là các căn thực sự khớp nguyên nhân trong `unit_diagnostic_causes` (không độn).
