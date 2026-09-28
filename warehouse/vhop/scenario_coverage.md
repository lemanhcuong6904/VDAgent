# Ma trận bao phủ kịch bản — Vinhomes Ocean Park

- Snapshot: `SNAP-20260630-01` (2026-06-30)
- Semantic version: `3.1.0`
- Tổng số căn: 3000
- Số chẩn đoán (AVAILABLE & DOM>90): 1139

| # | Mã nguyên nhân | Điều kiện kích hoạt | Số căn (primary) | unit_code mẫu |
|---|---|---|---|---|
| 1 | `LEGAL_PERMIT_BARRIER` | is_sales_permit_issued=FALSE OR is_bank_guarantee_issued=FALSE | 99 | BEVERLY-24.001, BEVERLY-27.002, BEVERLY-01.003, BEVERLY-29.004, BEVERLY-06.005 |
| 2 | `SEVERE_PHYSICAL_DEFECT` | physical_defect_penalty>=25 AND price_spread>=0 | 135 | SAPPHIRE1-13.001, SAPPHIRE1-23.002, SAPPHIRE1-04.003, SAPPHIRE1-27.008, SAPPHIRE1-09.010 |
| 3 | `EXTREME_THERMAL_EXPOSURE` | thermal_view_penalty>=40 AND subsidy<24 | 343 | SAPPHIRE1-04.003, SAPPHIRE1-12.009, SAPPHIRE1-05.017, SAPPHIRE1-21.018, SAPPHIRE1-25.023 |
| 4 | `SECONDARY_ARBITRAGE` | secondary_price_gap_pct>=10 AND comp trong 90 ngày | 214 | SAPPHIRE1-13.001, SAPPHIRE1-23.002, SAPPHIRE1-27.008, SAPPHIRE1-13.011, SAPPHIRE1-11.014 |
| 5 | `LUMP_SUM_TICKET_BARRIER` | ticket_ratio>=15 AND \|price_spread\|<=10 | 10 | ZURICH-24.001, ZURICH-19.002, ZURICH-09.003, ZURICH-07.004, ZURICH-12.006 |
| 6 | `OVERPRICED_VS_PEER` | price_spread>=10 AND defect<=24 | 31 | SAPPHIRE1-10.040, SAPPHIRE1-21.062, SAPPHIRE1-18.065, SAPPHIRE1-16.101, SAPPHIRE1-28.103 |
| 7 | `LOW_SALES_INCENTIVE` | commission<=1.5 AND spiff rỗng AND views<50 | 110 | SAPPHIRE1-12.032, SAPPHIRE1-24.043, SAPPHIRE1-24.050, SAPPHIRE1-08.063, SAPPHIRE1-10.077 |
| 8 | `DEEP_FUNNEL_DROP_OFF` | dropoff>=60 AND bookings>=5 AND views>=300 AND visits>=10 | 197 | SAPPHIRE1-13.001, SAPPHIRE1-23.002, SAPPHIRE1-04.003, SAPPHIRE1-02.004, SAPPHIRE1-26.005 |

## Ghi chú
- Ngưỡng lấy từ `semantic_config`; các giá trị `PENDING` cần xác nhận.
- `attribution_score` của mỗi `diagnostic_id` luôn có tổng = 1.000.
- `unit_code` mẫu là các căn thực sự khớp nguyên nhân trong `unit_diagnostic_causes` (không độn).
