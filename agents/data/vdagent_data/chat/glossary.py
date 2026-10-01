"""What the words of a Data package mean, for the person asking.

Every entry comes from this agent's own vocabulary (`vocab.py`, the entity ladder, the limitation codes) or from the package
itself (thresholds). A number such as the overdue threshold is quoted from the package's `semantic_config`, never from here;
a term that is not known is reported as not found, never explained from memory.
"""

from __future__ import annotations

from typing import Any

from vdagent_data import vocab
from vdagent_data.resolve import name_form

MAX_MATCHES = 5

_METRIC = {
    "unit_count": "Số căn trong tập dữ liệu.",
    "avg_dom_unsold": "Số ngày tồn trung bình của các căn đang mở bán (AVAILABLE), tính từ cột unsold_days_dom.",
    "slow_moving_count": "Số căn đang mở bán có số ngày tồn lớn hơn ngưỡng overdue_threshold_days.",
    "slow_moving_rate": "Tỷ lệ phần trăm căn đang mở bán là bán chậm, trên tổng số căn đang mở bán.",
    "avg_net_price_per_m2": "Giá ròng trung bình trên mỗi m² của các căn.",
    "absorption_rate": "Tỷ lệ phần trăm căn đã bán (SOLD) trên tổng số căn.",
    "dom_days": "Số ngày căn tồn chưa bán (unsold_days_dom); với một nhóm căn là trung vị.",
    "net_price_per_m2_vnd": "Giá ròng trên mỗi m² (VND); với một nhóm căn là trung vị.",
    "asking_price_vnd": "Giá chào bán (VND); với một nhóm căn là trung vị.",
    "net_area_m2": "Diện tích ròng (m²), diện tích dùng để chọn nhóm căn tương đồng.",
    "discount_pct": "Mức chiết khấu (%), lấy từ dòng tồn kho nếu kho có cột này.",
    "subsidy_duration_mo": "Thời gian hỗ trợ lãi suất (số tháng), lấy từ dòng tồn kho nếu kho có cột này.",
}

# metrics only the single-unit path writes (`steps.UNIT_METRICS`), with their unit
_UNIT_METRIC = {
    "inquiry_leads_30d": ("COUNT", ("Số lead hỏi mua của căn trong 30 ngày tính đến ngày chốt, cộng từ bảng phễu bán hàng theo ngày; "
                                    "chỉ có khi bảng phễu phủ đủ 30 ngày.")),
    "dw_peer_n": ("COUNT", "Số căn tương đồng mà kho dữ liệu đã lưu sẵn cho căn này (cột peer_n của bảng chẩn đoán); Data không tự tính con số này."),
}

# the figures of one unit worth telling, with what each column is; `inventory` columns come from the inventory row of the
# snapshot, `unit` columns from the unit's master row
UNIT_FIGURES: tuple[tuple[str, str, str], ...] = (
    ("inventory_status", "inventory", "Trạng thái tồn kho của căn ở kỳ chốt: AVAILABLE, BOOKED hoặc SOLD."),
    ("unsold_days_dom", "inventory", "Số ngày căn tồn chưa bán (DOM), lấy từ dòng tồn kho ở kỳ chốt."),
    ("net_price_per_m2", "inventory", "Giá ròng trên mỗi m² (VND/m²), lấy từ dòng tồn kho ở kỳ chốt."),
    ("asking_price_vnd", "inventory", "Giá chào bán của căn (VND), lấy từ dòng tồn kho ở kỳ chốt."),
    ("discount_pct", "inventory", "Mức chiết khấu (%), lấy từ dòng tồn kho ở kỳ chốt."),
    ("subsidy_duration_mo", "inventory", "Thời gian hỗ trợ lãi suất (số tháng), lấy từ dòng tồn kho ở kỳ chốt."),
    ("net_area_m2", "unit", "Diện tích ròng của căn (m²), lấy từ bảng căn; dùng để chọn nhóm căn tương đồng."),
    ("area_m2", "unit", "Diện tích gộp của căn (m²), lấy từ bảng căn; khác diện tích ròng net_area_m2."),
    ("unit_type", "unit", "Loại căn."),
    ("floor_no", "unit", "Số tầng của căn."),
    ("floor_band", "unit", "Nhóm tầng của căn."),
    ("balcony_orientation", "unit", "Hướng ban công của căn."),
)

# why a package holds the units it holds: the `population.rule` of a dataset
POPULATION_TEXT = {
    "subject": "Chỉ căn được hỏi.",
    "peer_candidates": ("Căn được hỏi cùng các căn ứng viên trong phạm vi quyền của bạn (tiêu chí lọc ứng viên nằm ở details.candidate_filter "
                        "hoặc details.criteria). Đây mới là danh sách ứng viên, chưa phải nhóm căn tương đồng cuối cùng."),
    "entities": "Các đối tượng (căn, phân khu, dự án) mà yêu cầu nêu tên, trong phạm vi quyền của bạn.",
    "filters": "Các căn khớp bộ lọc của yêu cầu, trong phạm vi quyền của bạn.",
}

_FILTER = {
    "released": "Căn đã mở bán: mọi dòng tồn kho của kỳ chốt.",
    "available": "Căn còn hàng, trạng thái tồn kho AVAILABLE.",
    "booked": "Căn có trạng thái tồn kho BOOKED.",
    "sold": "Căn đã bán, trạng thái tồn kho SOLD.",
}

METHOD_TEXT = {
    "exact": "Từ được viết khớp nguyên văn tên hoặc mã của đối tượng trong phạm vi quyền.",
    "normalized": "Khớp sau khi chuẩn hóa: bỏ dấu, không phân biệt hoa thường, và với mã căn thì bỏ dấu gạch, dấu chấm, khoảng trắng.",
    "contains": "Tên được viết có đủ các từ nằm trong tên của đối tượng.",
    "saved_choice": "Đối tượng này do người dùng chọn ở câu hỏi lại trước đó trong cùng lần chạy.",
    "subject_unit_code": "Phiếu giao việc nêu thẳng mã căn, không cần nhận diện.",
}

_LIMITATION = {
    "METRIC_UNAVAILABLE": ("Data không đọc được cột để tính chỉ số này qua lớp đọc dữ liệu chuẩn, nên giá trị để trống, không điền 0; "
                           "chưa chắc cột đó không có ở kho gốc."),
    "WINDOW_INCOMPLETE": "Dữ liệu phễu không phủ đủ cửa sổ 30 ngày nên không cộng số liệu; để trống thay vì điền thiếu.",
    "DQ_MISSING": "Có dòng thiếu giá trị của trường này.",
    "DQ_VIOLATION": "Có dòng vi phạm một kiểm tra chất lượng bù (ví dụ căn đã bán nhưng thiếu ngày bán).",
    "PEER_AREA_UNAVAILABLE": "Có căn thiếu diện tích ròng nên bị loại khỏi danh sách ứng viên tương đồng.",
    "PEER_CRITERION_UNAVAILABLE": "Căn mục tiêu thiếu thông tin cho một tiêu chí chọn căn tương đồng nên tiêu chí đó không áp dụng.",
    "SYNTHETIC_SOURCE": "Trường này là dữ liệu mô phỏng, không phải số thật của kho.",
    "PROVISIONAL_DEFINITION": "Định nghĩa chưa được team DATA duyệt, kết quả là tạm thời.",
    "CONFIG_PENDING": "Ngưỡng nghiệp vụ chưa được duyệt, kết quả dùng ngưỡng này là tạm thời.",
    "SMALL_SAMPLE": "Mẫu nhỏ hơn số tối thiểu đã duyệt, cần đọc kết quả thận trọng.",
    "SNAPSHOT_STATUS_ASSUMED": "Kho không có cột trạng thái duyệt của kỳ chốt; coi là đã duyệt, chờ team DATA xác nhận.",
    "MACRO_MONTH_MISSING": "Bảng vĩ mô chưa có tháng này, dùng tháng gần nhất có dữ liệu.",
    "INFRA_MISSING": "Dự án chưa có dữ liệu hạ tầng.",
    "EMPTY_RESULT": "Không có dòng nào khớp yêu cầu.",
    "OUT_OF_CATALOG_NEED_NOT_SERVED": "Nhu cầu ngoài danh mục của Data chưa được phục vụ; phần trong danh mục đã làm.",
    "BLOCKED": "Việc này đang chờ một quyết định nghiệp vụ nên chưa áp dụng.",
}


def _entry(term: str, kind: str, meaning: str, **more: Any) -> dict[str, Any]:
    return {"term": term, "kind": kind, "meaning": meaning, **more}


def _metric_entries() -> list[dict[str, Any]]:
    out = []
    for name, m in vocab.METRICS_V1.items():
        meaning = f"{_METRIC[name]} Đơn vị {m.unit}, thống kê {m.statistic}."
        if m.provisional:
            meaning += " Định nghĩa tạm thời, chưa được team DATA duyệt."
        out.append(_entry(name, "metric", meaning, unit=m.unit, statistic=m.statistic))
    out += [_entry(name, "metric", f"{text} Đơn vị {unit}.", unit=unit) for name, (unit, text) in _UNIT_METRIC.items()]
    return out


def _filter_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    out = [_entry(name, "filter", text) for name, text in _FILTER.items()]
    slow = config.get("overdue_threshold_days")
    limit = f"ngưỡng overdue_threshold_days = {slow['value']} ({slow['status']})" if slow else "ngưỡng overdue_threshold_days (không có trong dữ liệu đã lấy)"
    out.append(_entry("slow_moving", "filter", f"Căn đang mở bán (AVAILABLE) có số ngày tồn (unsold_days_dom) lớn hơn {limit}."))
    return out


def _entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *_metric_entries(),
        *_filter_entries(config),
        *(_entry(code, "limitation", text) for code, text in _LIMITATION.items()),
        *(_entry(name, "match_method", text) for name, text in METHOD_TEXT.items()),
        *(_entry(key, "threshold", f"Ngưỡng nghiệp vụ {key} = {v['value']} (trạng thái {v['status']}).", value=v["value"], status=v["status"])
          for key, v in config.items()),
    ]


def metric_meaning(metric_id: str) -> str | None:
    """What a metric of a package is, or `None` when the glossary does not know it (it is then not explained from memory)."""
    return next((e["meaning"] for e in _metric_entries() if e["term"] == metric_id), None)


def define(term: str, semantic_config: dict[str, Any]) -> dict[str, Any]:
    """The entries whose name is `term` or contains all its words (the exact ones first), at most `MAX_MATCHES`."""
    wanted = name_form(term)
    words = set(wanted.split())
    if not words:
        return {"found": False, "matches": []}
    found = []
    for entry in _entries(semantic_config):
        form = name_form(entry["term"])
        if form == wanted:
            found.append((0, entry))
        elif words <= set(form.split()):
            found.append((1, entry))
    matches = [e for _, e in sorted(found, key=lambda t: t[0])][:MAX_MATCHES]
    return {"found": bool(matches), "matches": matches}
