# Scenario Coverage — Central Master Dataset (M4)

Nguồn: `warehouse/dataset/` (Mart `dm_unit_friction_diagnostics` + Bridge `unit_diagnostic_causes`), snapshot **2026-06-30**, dataset_version **3.1.0**.

- Tổng diagnostic (Mart): **5051**  |  tổng dòng quy kết (Bridge): **10797**
- Chẩn đoán chỉ cho căn AVAILABLE & unsold_days_dom > 90 tại snapshot đóng băng 20260630.

## 1. Phủ 8/8 core cause

| # | cause_code (priority) | primary trong Mart | dòng trong Bridge | Trạng thái |
|---|---|---:|---:|:--:|
| 1 | `LEGAL_PERMIT_BARRIER` | 2395 | 2395 | ✅ |
| 2 | `SEVERE_PHYSICAL_DEFECT` | 406 | 1402 | ✅ |
| 3 | `EXTREME_THERMAL_EXPOSURE` | 691 | 1587 | ✅ |
| 4 | `SECONDARY_ARBITRAGE` | 257 | 2126 | ✅ |
| 5 | `LUMP_SUM_TICKET_BARRIER` | 122 | 254 | ✅ |
| 6 | `OVERPRICED_VS_PEER` | 159 | 435 | ✅ |
| 7 | `LOW_SALES_INCENTIVE` | 569 | 1564 | ✅ |
| 8 | `DEEP_FUNNEL_DROP_OFF` | 321 | 903 | ✅ |

**Phủ core: 8/8.**

## 2. Mã fallback ngoài 8 core (hợp lệ — không phải UNEXPLAINED)

Engine dùng khi thiếu mẫu peer hoặc đa yếu tố hòa; vẫn là *cause* hợp lệ nên không vi phạm gate '0 UNEXPLAINED'.

| cause_code | primary trong Mart | dòng trong Bridge |
|---|---:|---:|
| `INSUFFICIENT_PEER_DATA` | 3 | 3 |
| `MULTI_FACTOR_UNCLASSIFIED` | 128 | 128 |

## 3. Phân bố diagnostic theo dự án

| project_key | Dự án | # diagnostic (primary) |
|---|---|---:|
| 100 | Ocean Park (OCP) | 1114 |
| 200 | Smart City (SMC) | 316 |
| 300 | Grand Park (VGP) | 347 |
| 400 | Masteri (MAS) | 897 |
| 500 | Rui ro Phap ly (TST) | 2377 |
| — | **Tổng** | **5051** |

## 4. Gate nghiệm thu M4 (xem `tests/m4_verify_gates.py`)

- **G1** Σ attribution_score = 1.000 cho mỗi diagnostic_id — PASS
- **G2** Phủ đủ 8/8 core cause (gồm LEGAL_PERMIT_BARRIER) — PASS
- **G3** 0 UNEXPLAINED (mọi căn AVAILABLE & DOM>90 có diagnostic; Mart↔Bridge nhất quán) — PASS
- **G4** snapshot_date_key toàn bộ = 20260630; version 3.1.0; FK Mart/Bridge hợp lệ — PASS
