"""Deterministic Vietnamese chat adapter for the VHOP Compare demo."""
from __future__ import annotations
import asyncio
import json
import re
import unicodedata
from typing import Any
from .vh_service import CompareService, LABELS
from .vh_sufficiency import LEVEL_LABELS

UNIT = re.compile(r"\b[A-Z][A-Z0-9]*-\d+(?:\.\d+)?\b", re.I)
ZONE = re.compile(r"\bZN-[A-Z0-9-]+\b", re.I)
PROJECT = re.compile(r"\bPRJ-[A-Z0-9-]+\b", re.I)
TYPE = re.compile(r"\b(?:STUDIO|1PN|2PN|3PN|4PN)\b", re.I)
AREA_BAND = re.compile(r"DIEN TICH.{0,20}?(?:\u00b1|\+/-|\+-)\s*(\d+(?:[.,]\d+)?)\s*%")
PEER_TABLE_METRICS = ("net_asking_price_per_m2", "dom", "inquiry_leads_30d",
                      "discount_pct", "subsidy_duration_mo")
HELP = ("Ví dụ: 'So sánh căn SAPPHIRE1-13.001 với các căn tương đồng'; "
        "'So sánh A12-08 với A12-11'; 'Xếp hạng DOM của SAPPHIRE1-13.001'; "
        "'So sánh DOM 2PN theo tầng trong PRJ-VHOP'. "
        "Bạn cũng có thể dán JSON Compare request.")

def parse_request(message: str) -> dict[str, Any] | None:
    message = message.strip()
    if message.startswith("{"):
        try:
            request = json.loads(message)
        except json.JSONDecodeError:
            return None
        return request if isinstance(request, dict) else None

    upper = message.upper()
    plain = "".join(
        char for char in unicodedata.normalize("NFD", upper.replace("Đ", "D"))
        if not unicodedata.combining(char)
    )
    units = list(dict.fromkeys(m.upper() for m in UNIT.findall(upper)))
    zones = list(dict.fromkeys(m.upper() for m in ZONE.findall(upper)))
    projects = list(dict.fromkeys(m.upper() for m in PROJECT.findall(upper)))
    if len(units) > 2 or len(zones) > 2 or len(projects) > 1 or (units and zones):
        return None
    if units:
        subject = {"entityType": "unit", "entityCode": units[0]}
    elif zones:
        subject = {"entityType": "zone", "entityCode": zones[0]}
    elif projects:
        subject = {"entityType": "project", "entityCode": projects[0]}
    else:
        return None

    request: dict[str, Any] = {"subject": subject}
    metrics = []
    if "GIA" in plain or "PRICE" in plain:
        metrics.append("net_asking_price_per_m2")
    if "DOM" in plain or "TON" in plain:
        metrics.append("dom")
    if "QUAN TAM" in plain or "LEAD" in plain:
        metrics.append("inquiry_leads_30d")
    if "UU DAI" in plain or "CHIET KHAU" in plain:
        metrics.append("discount_pct")
    if "UU DAI" in plain or "HO TRO LAI SUAT" in plain:
        metrics.append("subsidy_duration_mo")
    if metrics:
        request["metricsRequested"] = metrics

    if len(units) == 2:
        request["comparisonMode"] = "head_to_head"
        request["targets"] = [{"entityType": "unit", "entityCode": units[1]}]
    elif len(zones) == 2:
        request["comparisonMode"] = "head_to_head"
        request["targets"] = [{"entityType": "zone", "entityCode": zones[1]}]
    elif "THI TRUONG" in plain:
        request["comparisonMode"] = "external_benchmark"
    elif any(word in plain for word in ("XEP HANG", "THU MAY", "TOP ", "RANKING")):
        request["comparisonMode"] = "ranking"
        request.setdefault("metricsRequested", ["dom"])
        top = re.search(r"\bTOP\s+(\d+)\b", plain)
        if top:
            request["rankingOptions"] = {"topN": int(top.group(1))}
    elif any(word in plain for word in ("THEO NHOM", "THEO TANG", "THEO HUONG",
                                          "THEO VIEW", "THEO PHAN KHU", "COHORT")):
        request["comparisonMode"] = "cohort"
        request["cohortDimension"] = (
            "balcony_orientation" if "HUONG" in plain else
            "view_type" if "VIEW" in plain else
            "zone_id" if "PHAN KHU" in plain else "floor_band")
    elif subject["entityType"] != "unit":
        request["comparisonMode"] = "ranking"
        request.setdefault("metricsRequested", ["dom"])
    else:
        request["comparisonMode"] = "peer_group"

    must_match = []
    if "CUNG PHAN KHU" in plain:
        must_match.append("zone_id")
    if "CUNG HUONG" in plain:
        must_match.append("balcony_orientation")
    if "CUNG VIEW" in plain:
        must_match.append("view_type")
    area = AREA_BAND.search(plain)
    if ("CHI VOI" in plain or "CHI CAC" in plain) and not (must_match or area):
        return None
    if (must_match or area) and request["comparisonMode"] != "peer_group":
        return None
    if must_match or area:
        override: dict[str, Any] = {}
        if must_match:
            override["mustMatch"] = must_match
        if area:
            override["areaBandPct"] = float(area.group(1).replace(",", "."))
        request["criteriaOverride"] = override
    if request["comparisonMode"] == "peer_group" and not metrics:
        request["metricsRequested"] = list(PEER_TABLE_METRICS)

    unit_type = TYPE.search(upper)
    if unit_type:
        request["unitTypeFilter"] = unit_type.group().upper()
    return request

def _num(value: Any) -> str:
    if value is None:
        return "không xác định"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")
    return str(value)

def _table(headers: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |",
                      *["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]])


STATUS_LABELS = {
    "VALID": "Hoàn tất", "PARTIAL": "Hoàn tất một phần",
    "INVALID": "Không hợp lệ",
}
CONFIDENCE_LABELS = {
    "high": "cao", "medium": "trung bình", "low": "thấp", "none": "chưa xác định",
}
POSITION_LABELS = {
    "better": "tốt hơn", "inline": "ngang", "worse": "kém hơn",
    "higher": "cao hơn", "lower": "thấp hơn",
}
MODE_LABELS = {
    "peer_group": "nhóm tương đồng", "head_to_head": "so trực diện",
    "cohort": "so theo nhóm", "ranking": "xếp hạng",
    "external_benchmark": "so với thị trường",
}


def render(result: dict[str, Any]) -> str:
    cmp = result["comparison"]
    mode = cmp["comparisonMode"]
    status = ("Cần làm rõ yêu cầu" if cmp.get("reason_code") == "CLARIFICATION_NEEDED"
              else STATUS_LABELS.get(cmp["status"], cmp["status"]))
    lines = [f"### Kết quả Compare · {MODE_LABELS.get(mode, mode)}",
             f"Trạng thái: **{status}**. "
             f"Snapshot: {cmp['snapshot_refs'][0]}; cấu hình: {cmp['semantic_config_version']}."]
    if cmp.get("reason") and not cmp.get("clarification"):
        lines.append(cmp["reason"])
    if cmp.get("clarification"):
        choice = cmp["clarification"]
        lines.append(choice["question"] + " " + ", ".join(
            option.get("entityCode") or option["entityId"] for option in choice["options"]
        ))
    sufficiency = cmp.get("dataSufficiency")
    if sufficiency:
        lines.append(f"Mức dữ liệu: **{LEVEL_LABELS[sufficiency['level']]}**. {sufficiency['summary']}")
    if mode == "peer_group" and result["peer_definition"]:
        peer = result["peer_definition"]
        if cmp.get("reason_code") == "INSUFFICIENT_EVIDENCE":
            lines.append(
                f"**Không đủ nhóm so sánh:** chỉ có {peer['peerCount']} căn tương đồng; "
                "cần tối thiểu 5 căn để kết luận."
            )
            attempts = peer.get("attemptedCriteria", [])
            if attempts:
                lines.append("Số căn từng bậc: " + "; ".join(
                    f"bậc {step['level']}: {step['peerCount']} căn" for step in attempts
                ) + ".")
            if cmp.get("suggestedNextSteps"):
                lines.append("Có thể hỏi cách khác:\n" + "\n".join(
                    "- " + step["label"] for step in cmp["suggestedNextSteps"]))
        else:
            lines.append(
                f"**Nhóm tương đồng:** {peer['peerCount']} căn; "
                f"độ tin cậy {CONFIDENCE_LABELS.get(cmp['confidence'], cmp['confidence'])}."
            )
            if cmp["metrics"]:
                lines.append(_table(
                    ["Chỉ số", "Căn", "Trung vị nhóm", "Chênh", "Chênh %", "Hạng"],
                    [[LABELS[row["metric"]][0], _num(row["subjectValue"]),
                      _num(row["benchmark"]["value"]), _num(row["absGap"]),
                      _num(row["pctGap"]), f"{row['rankInGroup']}/{row['groupSize']}"]
                     for row in cmp["metrics"]]
                ))
            values = cmp.get("peerValues", [])
            if values:
                available = set().union(*(row["values"] for row in values))
                order = [*PEER_TABLE_METRICS, *(key for key in sorted(available) if key not in PEER_TABLE_METRICS)]
                columns = [metric for metric in order if metric in available]
                lines.append("**Bảng từng căn:**")
                lines.append(_table(
                    ["Căn", *(LABELS.get(metric, (metric,))[0] for metric in columns)],
                    [[row["entityCode"], *(_num(row["values"].get(metric)) for metric in columns)]
                     for row in values]
                ))
            if cmp.get("notableDifferences"):
                lines.append("**Điểm đáng chú ý:**\n" + "\n".join(
                    "- " + item["statement"] for item in cmp["notableDifferences"]
                ))
            if peer["peers"]:
                lines.append("Căn tương đồng: " + ", ".join(
                    row["entityCode"] for row in peer["peers"][:10]
                ) + ".")
    elif mode == "head_to_head" and cmp.get("headToHead"):
        direct = cmp["headToHead"]
        if direct.get("peerRuleMatch") is not None:
            lines.append(f"Đạt luật nhóm tương đồng: **{'có' if direct['peerRuleMatch'] else 'không'}**.")
        if direct["rows"]:
            lines.append(_table(
                ["Chỉ số", "Đối tượng", "Đích", "Chênh", "Chênh %", "Vị trí"],
                [[LABELS.get(row["metric"], (row["metric"],))[0], _num(row["subjectValue"]),
                  _num(row["targetValue"]), _num(row["absGap"]), _num(row["pctGap"]),
                  POSITION_LABELS.get(row["position"], row["position"])]
                 for row in direct["rows"]]
            ))
    elif mode == "cohort" and cmp.get("cohorts"):
        cohort = cmp["cohorts"]
        lines.append(f"**Chia theo {cohort['dimension']} · {cohort['unitTypeFilter']}**")
        rows = []
        for group in cohort["groups"]:
            for row in group["metrics"]:
                rows.append([group["key"], LABELS.get(row["metric"], (row["metric"],))[0],
                             _num(row["benchmark"]["value"]), row["benchmark"]["n"],
                             _num(row["pctGap"]), f"{row['rank']}/{row['of']}"])
        if rows:
            lines.append(_table(["Nhóm", "Chỉ số", "Trung vị", "n", "Chênh %", "Hạng"], rows))
    elif mode == "ranking" and cmp.get("rankingList"):
        ranking = cmp["rankingList"]
        lines.append(
            f"**{LABELS[ranking['basis']][0]}:** {ranking['distribution']['n']} căn; "
            f"trung vị {_num(ranking['distribution']['value'])}; "
            f"độ tin cậy {CONFIDENCE_LABELS.get(cmp['confidence'], cmp['confidence'])}."
        )
        position = ranking.get("subjectPosition")
        if position:
            lines.append(
                f"**{position['entityCode']}**: hạng {position['rank']}/{position['of']}, "
                f"phân vị {_num(position['percentile'])}%."
            )
        if ranking["basis"] == "dom":
            lines.append("Danh sách dưới đây là các căn có DOM cao nhất; hạng 1 là DOM thấp nhất.")
        lines.append(_table(
            ["Hạng", "Căn", "Giá trị"],
            [[row["rank"], row["entityCode"], _num(row["value"])] for row in ranking["rows"]]
        ))
    if cmp.get("limitations"):
        lines.append("Giới hạn: " + " ".join(cmp["limitations"]))
    lines.append(f"Chứng cứ: {cmp['artifact_id']} · {cmp['content_hash'][:12]}.")
    return "\n\n".join(lines)


def answer(message: str, service: CompareService | None = None) -> str:
    request = parse_request(message)
    if request is None:
        return HELP
    try:
        return render((service or CompareService()).run(request))
    except (KeyError, TypeError, ValueError) as exc:
        return f"Yêu cầu chưa hợp lệ: {exc}. {HELP}"
