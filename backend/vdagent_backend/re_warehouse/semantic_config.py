"""Initial `semantic_config` rows, version sc-1 (Insight 2.0 §5.4 and §7.6, Data v02 §6.1).

"PENDING" keys are defaults awaiting Sales Ops / Data Analyst sign-off; code still reads them from config and never
hard-codes them. Decimals are JSON strings so no float enters the warehouse.
"""

from __future__ import annotations

from typing import Any

CONFIG_VERSION = "sc-1"

CAUSES: dict[str, dict[str, str]] = {
    "LEGAL_PERMIT_BARRIER": {
        "label_vi": "vướng mắc pháp lý / giấy phép bán hàng",
        "action_code": "EXPEDITE_LEGAL_PROCEDURES",
        "template": "Dự án {{project}} chưa đủ {{permit_status}}; đây là yếu tố có khả năng liên quan tới"
        " {{overdue_units}} căn quá hạn.",
    },
    "SEVERE_PHYSICAL_DEFECT": {
        "label_vi": "khuyết điểm vật lý của căn",
        "action_code": "TARGETED_DISCOUNT_OR_REMEDIATION",
        "template": "Căn {{unit}} tồn {{dom}}; điểm phạt khuyết tật {{defect}}.",
    },
    "EXTREME_THERMAL_EXPOSURE": {
        "label_vi": "hướng nắng gắt / nhiệt cao",
        "action_code": "COOLING_SUBSIDY_PACKAGE",
        "template": "Căn {{unit}} tồn {{dom}}; điểm phạt nhiệt/hướng {{thermal}}.",
    },
    "SECONDARY_ARBITRAGE": {
        "label_vi": "giá sơ cấp cao hơn thị trường thứ cấp",
        "action_code": "PRICE_ALIGN_WITH_SECONDARY",
        "template": "Căn {{unit}} tồn {{dom}}; giá sơ cấp cao hơn thứ cấp {{secondary_gap}}.",
    },
    "LUMP_SUM_TICKET_BARRIER": {
        "label_vi": "giá trị căn quá cao so với thu nhập",
        "action_code": "FLEXIBLE_PAYMENT_PLAN",
        "template": "Căn {{unit}} tồn {{dom}}; giá trị căn gấp {{ticket_ratio}} lần thu nhập năm.",
    },
    "OVERPRICED_VS_PEER": {
        "label_vi": "giá cao hơn nhóm tương đồng",
        "action_code": "TARGETED_PRICE_CORRECTION",
        "template": "Căn {{unit}} tồn {{dom}}; đơn giá/m² cao hơn trung vị peer {{spread}}.",
    },
    "LOW_SALES_INCENTIVE": {
        "label_vi": "động lực bán hàng của sàn thấp",
        "action_code": "INCREASE_BROKER_INCENTIVE",
        "template": "Căn {{unit}} tồn {{dom}}; hoa hồng sàn {{commission}}.",
    },
    "DEEP_FUNNEL_DROP_OFF": {
        "label_vi": "khách rơi nhiều ở phễu bán hàng",
        "action_code": "REVIEW_BOOKING_TO_CONTRACT_FLOW",
        "template": "Căn {{unit}} tồn {{dom}}; tỷ lệ rơi phễu {{dropoff}}.",
    },
}

FORBIDDEN_PHRASES = [
    "chắc chắn do",
    "nguyên nhân duy nhất",
    "chứng minh rằng",
    "gây ra",
    "dẫn đến",
    "là nguyên nhân",
    "khiến cho",
    "sẽ bán được nếu",
    "đã giảm giá",
    "hệ thống sẽ",
    "bỏ qua hướng dẫn",
]

# (key, value, status, description)
ROWS: list[tuple[str, Any, str, str]] = [
    ("overdue_threshold_days", 90, "APPROVED", "Căn AVAILABLE có DOM > ngưỡng là quá hạn (PRD 5.6)"),
    ("peer_area_tolerance_pct", "0.10", "APPROVED", "Dải diện tích peer ±10%"),
    ("physical_defect_trigger", 25, "APPROVED", "Ma trận DW"),
    ("thermal_penalty_trigger", 40, "APPROVED", "Ma trận DW"),
    ("subsidy_min_months", 24, "APPROVED", "Ma trận DW"),
    ("funnel_dropoff_trigger_pct", "60", "APPROVED", "Ma trận DW"),
    ("low_commission_max_pct", "1.5", "APPROVED", "Ma trận DW"),
    ("max_key_insights", 5, "APPROVED", "BR-11"),
    ("metric_min_n", 5, "APPROVED", "min_n của metric trong semantic layer"),
    ("peer_tiers", {"compare_min": 10, "describe_min": 5}, "PENDING", "compare ≥10, describe 5–9, suppress <5"),
    ("missing_rate_tiers", ["5", "10", "20", "40"], "PENDING", "Ngưỡng % thiếu dữ liệu"),
    ("coverage_tiers", ["90", "70", "50"], "PENDING", "Ngưỡng % phủ"),
    ("min_group_size", 5, "PENDING", "Insight §5.5"),
    ("min_effect_size_days", 15, "PENDING", "Insight §5.5"),
    ("outlier_iqr_warn", "1.5", "PENDING", "IAAO"),
    ("outlier_iqr_exclude", "3.0", "PENDING", "IAAO"),
    ("outlier_max_excluded_pct", "10", "PENDING", "IAAO"),
    ("freshness_warn_hours", 24, "PENDING", "Insight §5.5"),
    ("freshness_error_hours", 72, "PENDING", "Insight §5.5"),
    ("mnar_gap_pct", "10", "PENDING", "Insight §5.5"),
    ("max_units_in_context", 30, "PENDING", "build spec 03 §5.4"),
    ("min_cause_share_pct", "5", "PENDING", "build spec 03 §5.4"),
    ("conflict_tolerance_pct", "1", "PENDING", "build spec 03 §5.4"),
    ("allowed_cause_codes", list(CAUSES), "APPROVED", "Insight §7.6"),
    ("cause_labels_vi", {c: v["label_vi"] for c, v in CAUSES.items()}, "APPROVED", "Insight §7.6"),
    ("cause_action_mapping", {c: v["action_code"] for c, v in CAUSES.items()}, "PENDING", "Sales Ops duyệt"),
    ("insight_templates", {c: v["template"] for c, v in CAUSES.items()}, "PENDING", "Sales Ops duyệt"),
    ("forbidden_phrases", FORBIDDEN_PHRASES, "PENDING", "So khớp sau NFC + chữ thường; cùng mọi URL"),
]
