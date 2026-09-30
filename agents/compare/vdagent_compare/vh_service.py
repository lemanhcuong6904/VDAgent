"""Compare v5.1 service: deterministic artifacts over a Data Package.

This module has no model calls. It consumes the copied VHOP CSV pack or the small
hero fixture and returns serializable artifacts. The plugin only renders the result.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .vh_data import DataPackage, Unit, load_hero_package, load_package_for
from .vh_math import (
    DIRECTIONS, GROUP_ONLY, SOURCES, UNITS, benchmark, compare_value,
    confidence, magnitude, number, rounded, threshold,
)
from .vh_peers import FLOOR_BANDS, ORIENTATION_GROUP, UpstreamPeerSetError, build_peer_group, read_peer_set
from .vh_sufficiency import applies_to, assess

log = logging.getLogger(__name__)

HASH_EXCLUDE = {
    "artifact_id", "run_id", "task_id", "version", "input_artifact_refs",
    "peerDefinitionRef", "content_hash",
}
VALID_MODES = {"peer_group", "head_to_head", "cohort", "ranking", "external_benchmark"}
VALID_DIMENSIONS = {
    "floor_band", "balcony_orientation", "orientation_group",
    "view_type", "area_band", "zone_id",
}
DEFAULT_METRICS = ("net_asking_price_per_m2", "dom")
CAUSAL_LIMIT = "Kết quả mô tả chênh lệch, không hàm ý quan hệ nhân quả."
LABELS = {
    "net_asking_price_per_m2": ("Giá ròng/m²", "VND", "VND"),
    "asking_price_per_m2": ("Giá chào/m²", "VND", "VND"),
    "asking_price_vnd": ("Giá chào", "VND", "VND"),
    "dom": ("DOM", "ngày", "ngày"),
    "unsold_days": ("Số ngày tồn", "ngày", "ngày"),
    "inquiry_leads_30d": ("Lượt quan tâm 30 ngày", "lượt", "lượt"),
    "discount_pct": ("Chiết khấu", "%", "điểm %"),
    "subsidy_duration_mo": ("Hỗ trợ lãi suất", "tháng", "tháng"),
}
TYPE_QUESTION = "Phạm vi có nhiều loại căn. Bạn muốn so loại căn nào?"
MARKET_REASON = "Chưa có dữ liệu thị trường: DW v3.1.0 không có bảng dự án đối chiếu cùng phân khúc."
MARKET_NEXT_STEP = "ranking hoặc head_to_head giữa các phân khu / dự án nội bộ"
MUST_MATCH_LABEL = {
    "zone_id": "cùng phân khu", "view_type": "cùng view",
    "balcony_orientation": "cùng hướng ban công",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _seal(artifact: dict) -> dict:
    body = {key: value for key, value in artifact.items() if key not in HASH_EXCLUDE}
    artifact["content_hash"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    return artifact


def _format(value: int | float | None) -> str:
    if value is None:
        return "không xác định"
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{int(value):,}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _statement(code: str, row: dict) -> str:
    label, unit, gap_unit = LABELS[row["metric"]]
    delta = row["absGap"]
    sign = "cao hơn" if delta > 0 else "thấp hơn" if delta < 0 else "bằng"
    pct = ""
    if "thresholdAbs" not in row and row["pctGap"] is not None:
        p = row["pctGap"]
        pct = f" ({'+' if p > 0 else ''}{_format(p)}%)"
    return (
        f"{label} của {code} là {_format(row['subjectValue'])} {unit}, {sign} trung vị "
        f"{row['benchmark']['n']} căn tương đồng {_format(abs(delta))} {gap_unit}{pct}, "
        f"xếp {row['rankInGroup']}/{row['groupSize']}."
    )


def _metric_row(metric: str, value: Decimal, values: list[Decimal], bm: dict, package: DataPackage, min_n: int) -> dict:
    table, columns = SOURCES[metric]
    source_ref = {"table": table, "columns": columns, "filters": {"window_days": 30} if metric == "inquiry_leads_30d" else {}}
    return {
        "metric": metric, "unit": UNITS[metric], "direction": DIRECTIONS[metric],
        "subjectValue": number(value), "benchmark": bm,
        **compare_value(value, bm, values, metric, min_n),
        "computationId": f"comp_{metric}@{package.metric_artifact_id}",
        "sourceRef": source_ref,
    }


def _scope(raw: Mapping[str, Any]) -> dict:
    scope = raw.get("scope") or {}
    return {
        "userId": str(scope.get("userId") or "demo"),
        "allowedProjectIds": list(scope.get("allowedProjectIds") or []),
        "allowedZoneIds": list(scope.get("allowedZoneIds") or []),
    }


def _entity(unit: Unit) -> dict:
    return {"entityType": "unit", "entityId": unit.unit_id, "entityCode": unit.unit_code}


def _source_tables(metrics: list[dict]) -> list[str]:
    out = ["fact_unit_inventory_snapshot", "dim_unit_master"]
    for row in metrics:
        table = row["sourceRef"]["table"]
        if table not in out:
            out.append(table)
    return out


def _next_steps(subject: Unit, group: list[Unit]) -> list[dict]:
    """Level 3 (spec §2.4): other ways to answer, best first. Compare never runs them itself."""
    for_sale = [u for u in group if u.status == "available"]
    nearest = min(for_sale, key=lambda u: (abs(u.area_m2 - subject.area_m2), u.unit_id), default=None)
    steps = []
    if nearest:
        steps.append({
            "operation": "compare_head_to_head",
            "target": {"entityType": "unit", "entityId": nearest.unit_id, "entityCode": nearest.unit_code},
            "label": f"So trực diện {subject.unit_code} với căn gần giống nhất {nearest.unit_code}",
        })
    steps.append({
        "operation": "compare_ranking", "metrics": ["dom"], "unitTypeFilter": subject.unit_type,
        "label": f"Xếp hạng {subject.unit_code} theo DOM trong các căn {subject.unit_type} của dự án",
    })
    steps.append({
        "operation": "compare_cohort", "cohortDimension": "floor_band", "unitTypeFilter": subject.unit_type,
        "label": f"Xem các căn {subject.unit_type} theo nhóm tầng",
    })
    return steps


class CompareService:
    def __init__(self, root: Path | None = None, package: DataPackage | None = None):
        # None: find the CSV pack on first CSV question (hero questions never need it).
        self.root = root
        # WS3: a package built from canonical Data artifacts (stepspec.py); when set, no fixture or pack is loaded.
        self._package = package

    def _env(self, package: DataPackage, raw: Mapping[str, Any], kind: str,
             status: str, limitations: list[str], sources: list[str] | None = None,
             refs: list[str] | None = None) -> dict:
        run_id = str(raw.get("run_id") or "demo_" + hashlib.sha256(_canonical(dict(raw)).encode("utf-8")).hexdigest()[:12])
        input_refs = raw.get("input_artifact_refs") or {}
        if not isinstance(input_refs, dict):
            input_refs = {}
        metric_id = input_refs.get("metricArtifactId") or package.metric_artifact_id
        dq_id = input_refs.get("dqArtifactId") or package.dq_artifact_id
        return {
            "artifact_id": f"art_{'peerdef' if kind == 'peer_definition' else 'cmp'}_{run_id}",
            "run_id": run_id, "task_id": str(raw.get("task_id") or "demo_compare"),
            "artifact_type": kind, "schema_version": f"{kind}@1.0.0", "version": 1,
            "status": status, "producer": "compare_agent",
            "snapshot_refs": [str(raw.get("snapshot_id") or package.snapshot_id)],
            "source_refs": sources if sources is not None else ["fact_unit_inventory_snapshot", "dim_unit_master"],
            "input_artifact_refs": [metric_id, dq_id, *(refs or [])],
            "evidence_refs": [], "semantic_config_version": str(raw.get("semantic_config_version") or package.semantic_version),
            "limitations": limitations,
        }

    def _invalid(self, package: DataPackage, raw: Mapping[str, Any], mode: str, code: str, reason: str,
                 clarification: dict | None = None) -> dict:
        cmp = self._env(package, raw, "comparison", "INVALID", [], [])
        cmp.update({
            "reason_code": code, "reason": reason, "comparisonMode": mode,
            "metrics": [], "notableDifferences": [], "chartHints": [],
            "confidence": "none", "usedDefaults": [],
        })
        if clarification is not None:
            cmp["clarification"] = clarification
        return {"peer_definition": None, "comparison": _seal(cmp)}

    def run(self, raw: Mapping[str, Any]) -> dict:
        subject_ref = raw.get("subject")
        valid_subject = (
            isinstance(subject_ref, dict)
            and bool(subject_ref.get("entityCode") or subject_ref.get("entityId"))
            and all(isinstance(subject_ref.get(key), str)
                    for key in ("entityCode", "entityId") if subject_ref.get(key) is not None)
        )
        if not valid_subject:
            package = self._package or load_hero_package()  # no subject → no pack to pick; ids only
            return self._invalid(package, raw, str(raw.get("comparisonMode") or "peer_group"),
                                 "INVALID_INPUT", "Thiếu subject.entityCode hoặc subject.entityId.")
        package = self._package or load_package_for(subject_ref, self.root)
        mode = str(raw.get("comparisonMode") or "peer_group")
        if mode not in VALID_MODES:
            return self._invalid(package, raw, mode, "INVALID_INPUT", "Loại so sánh không được hỗ trợ.")
        for key in ("scope", "input_artifact_refs", "criteriaOverride", "rankingOptions"):
            if raw.get(key) is not None and not isinstance(raw[key], dict):
                return self._invalid(package, raw, mode, "INVALID_INPUT", f"{key} must be an object.")
        for key in ("allowedProjectIds", "allowedZoneIds"):
            value = (raw.get("scope") or {}).get(key)
            if value is not None and (
                not isinstance(value, list) or any(not isinstance(item, str) for item in value)
            ):
                return self._invalid(package, raw, mode, "INVALID_INPUT", f"scope.{key} must be a string list.")
        metrics = raw.get("metricsRequested")
        if metrics is not None and (
            not isinstance(metrics, list) or not metrics
            or any(not isinstance(item, str) for item in metrics)
        ):
            return self._invalid(package, raw, mode, "INVALID_INPUT", "metricsRequested must be a nonempty string list.")
        targets = raw.get("targets")
        if targets is not None and (
            not isinstance(targets, list) or any(not isinstance(item, dict) for item in targets)
        ):
            return self._invalid(package, raw, mode, "INVALID_INPUT", "targets must be an object list.")
        if raw.get("snapshot_id") and raw["snapshot_id"] != package.snapshot_id:
            return self._invalid(package, raw, mode, "DATASET_MISMATCH", "snapshot_id không khớp Data Package.")
        if raw.get("semantic_config_version") and raw["semantic_config_version"] != package.semantic_version:
            return self._invalid(package, raw, mode, "DATASET_MISMATCH", "semantic_config_version không khớp manifest.")
        refs = raw.get("input_artifact_refs") or {}
        if refs and (refs.get("metricArtifactId") != package.metric_artifact_id or refs.get("dqArtifactId") != package.dq_artifact_id):
            return self._invalid(package, raw, mode, "UPSTREAM_NOT_VALID", "Artifact đầu vào không thuộc Data Package.")
        if raw.get("dq_status", "VALID") != "VALID":
            return self._invalid(package, raw, mode, "UPSTREAM_QUALITY_FAILED", "DQ gate của Data Package không đạt.")
        scope = _scope(raw)
        if mode == "external_benchmark":
            return self._external(package, raw)
        if mode == "peer_group":
            return self._peer_group(package, raw, scope)
        if mode == "head_to_head":
            return self._head_to_head(package, raw, scope)
        if mode == "cohort":
            return self._cohort(package, raw, scope)
        return self._ranking(package, raw, scope)

    def _peer_group(self, package: DataPackage, raw: Mapping[str, Any], scope: dict) -> dict:
        ref = raw["subject"]
        if ref.get("entityType", "unit") != "unit":
            return self._invalid(package, raw, "peer_group", "INVALID_INPUT", "peer_group cần một căn.")
        subject, error, choices = package.resolve_unit(ref, scope)
        if error:
            clarification = (
                {"question": f'Có {len(choices)} căn khớp "{ref.get("entityCode")}". Bạn muốn so căn nào?',
                 "options": [{"entityId": u.unit_id, "entityCode": u.unit_code} for u in choices[:10]]}
                if choices else None
            )
            return self._invalid(package, raw, "peer_group", error, f"Không dùng được đối tượng {ref.get('entityCode') or ref.get('entityId')}.", clarification)
        assert subject is not None
        requested = list(raw.get("metricsRequested") or DEFAULT_METRICS)
        if not requested or any(metric not in DIRECTIONS for metric in requested):
            return self._invalid(package, raw, "peer_group", "INVALID_INPUT", "Danh sách chỉ số không hợp lệ.")
        applicable = [m for m in requested if m not in GROUP_ONLY]
        not_applicable = [m for m in requested if m in GROUP_ONLY]
        override = raw.get("criteriaOverride") or {}
        if set(override) - {"mustMatch", "areaBandPct"}:
            return self._invalid(package, raw, "peer_group", "INVALID_INPUT", "criteriaOverride có trường không hỗ trợ.")
        must_match = override.get("mustMatch") or []
        try:
            area_pct = Decimal(str(override.get("areaBandPct", package.approved_config.get("peer_area_tolerance_pct", "10"))))
            min_n = int(package.approved_config.get("min_peer_count", "5"))
            max_peers = raw.get("maxPeers", package.approved_config.get("max_peers"))
            max_peers = int(max_peers) if max_peers not in (None, "") else None
            if max_peers is not None and max_peers < 1:
                raise ValueError("INVALID_INPUT: maxPeers must be >= 1")
            pool, permission_count = package.candidate_pool(subject, scope)
            peer_set = raw.get("peerSet")
            if peer_set is not None:  # spec v5.3: Data chose the group; Compare does not re-filter
                if not isinstance(peer_set, dict):
                    raise ValueError("INVALID_INPUT: peerSet must be an object")
                rule_area = Decimal(str(package.approved_config.get("peer_area_tolerance_pct", "10")))
                outcome = read_peer_set(
                    subject, {u.unit_id: u for u in package.units}, peer_set, snapshot_id=package.snapshot_id,
                    scope=scope, area_pct=rule_area, min_peers=min_n, must_match=must_match,
                    area_override=area_pct if override.get("areaBandPct") is not None else None,
                    max_peers=max_peers,
                )
                permission_count = int(peer_set.get("permissionFilteredCount") or 0)
                self._cross_check(subject, pool, package, scope, rule_area, min_n, must_match, outcome)
            else:
                outcome = build_peer_group(
                    subject, pool, snapshot_id=package.snapshot_id, scope=scope, area_pct=area_pct,
                    min_peers=min_n, relax=bool(raw.get("relaxationLadderEnabled", True)), must_match=must_match,
                    max_peers=max_peers,
                )
        except UpstreamPeerSetError as exc:
            return self._invalid(package, raw, "peer_group", "UPSTREAM_NOT_VALID", str(exc))
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            return self._invalid(package, raw, "peer_group", "INVALID_INPUT", str(exc))
        causal = CAUSAL_LIMIT
        limits = []
        if outcome.peer_count < 30:
            limits.append(f"Cỡ mẫu n={outcome.peer_count}, khoảng dao động của benchmark còn rộng.")
        if outcome.relaxation["isPeerSampleConstrained"]:
            limits.append(f"Không đủ {min_n} căn cùng nhóm tầng; đã mở sang nhóm tầng liền kề.")
        if permission_count:
            limits.append(f"{permission_count} ứng viên bị loại do ngoài phạm vi quyền truy cập.")
        overrides = [MUST_MATCH_LABEL[d] for d in must_match]
        if override.get("areaBandPct") is not None:
            overrides.append(f"diện tích ±{number(area_pct)}%")
        if overrides:
            limits.append("Nhóm so sánh đã thu hẹp theo yêu cầu: " + ", ".join(overrides) + ".")
            if raw.get("peerSet") is not None:
                limits.append("Thu hẹp trong nhóm Data đã chọn; Compare không mở thêm nhóm tầng.")
        limits.append(causal)
        peer_ids = [row["entityId"] for row in outcome.peers]
        lookup = {unit.unit_id: unit for unit in package.units}
        rows = []
        dropped = []
        constrained = outcome.relaxation["isPeerSampleConstrained"]
        peer_units = [lookup[unit_id] for unit_id in peer_ids]
        # Below min_n the peers are not published, but the level still describes the real group.
        group = peer_units or sorted((lookup[i] for i in outcome.qualified_ids), key=lambda u: u.unit_id)
        sufficiency = assess(subject, group, applicable, constrained=constrained, min_peers=min_n)
        use = {row["metric"]: row for row in sufficiency["perMetric"]}
        # Không đủ nhóm (< min_n sau khi mở tầng) → không phát hành kết luận: không tính chỉ số nào.
        # (Trước đây vòng này vẫn chạy và ghi "Bỏ metric … do chỉ có 4 peer" — sai nghĩa, dữ liệu không thiếu.)
        for metric in (applicable if outcome.status == "VALID" else []):
            subject_value = subject.metrics.get(metric)
            values = [u.metrics[metric] for u in peer_units
                      if applies_to(metric, u) and u.metrics.get(metric) is not None]
            bm = benchmark(values, min_n) if subject_value is not None else None
            if bm is None:
                observed = len([u for u in package.units if u.unit_id in outcome.qualified_ids and u.metrics.get(metric) is not None])
                dropped.append(f"Bỏ metric {metric} do chỉ có {observed} peer có dữ liệu (<{min_n}).")
                continue
            if use[metric]["use"] == "dropped":  # ≥ min_n values but under half the group (spec §2.4)
                row = use[metric]
                dropped.append(f"Bỏ metric {metric} do chỉ {row['n']}/{row['applicable']} peer có dữ liệu "
                               f"({_format(row['coveragePct'])}% < 50%).")
                continue
            rows.append(_metric_row(metric, subject_value, values, bm, package, min_n))
        cmp_limits = limits[:-1] + dropped + [
            f"Bỏ chỉ số {metric}: chỉ có nghĩa ở cấp nhóm, không áp dụng cho một căn." for metric in not_applicable
        ] + [causal]
        status = "PARTIAL" if outcome.status != "VALID" or dropped or not_applicable else "VALID"
        insufficient = sufficiency["level"] == "INSUFFICIENT"
        peer_set = raw.get("peerSet") or {}
        upstream = [str(peer_set["packageId"])] if peer_set.get("packageId") else []
        pd = self._env(package, raw, "peer_definition", outcome.status, limits, refs=upstream)
        if outcome.reason_code:
            pd["reason_code"] = outcome.reason_code
        pd.update({
            "subject": dict(ref),
            "subjectProfile": {
                "unitType": subject.unit_type, "areaM2": number(subject.area_m2),
                "floorBand": subject.floor_band, "balconyOrientation": subject.balcony_orientation,
                "viewType": subject.view_type, "zoneId": subject.zone_id,
                "launchBatchId": subject.launch_batch_id,
            },
            "criteria": outcome.criteria, "relaxation": outcome.relaxation,
            "attemptedCriteria": outcome.attempts, "peers": outcome.peers,
            "peerCount": outcome.peer_count, "excludedPeers": outcome.excluded_peers,
            "excludedSummary": outcome.excluded_summary,
            "excludedByPermissionCount": permission_count, "outlierPolicy": "flag_only",
            "confidence": confidence(outcome.peer_count, min_n, outcome.relaxation["isPeerSampleConstrained"]),
        })
        pd = _seal(pd)
        cmp = self._env(package, raw, "comparison", status, cmp_limits, _source_tables(rows),
                        [*upstream, pd["artifact_id"]])
        cmp["evidence_refs"] = [row["computationId"] for row in rows]
        reason_code = outcome.reason_code or (
            "INSUFFICIENT_EVIDENCE" if insufficient and not rows else
            "METRIC_NOT_APPLICABLE" if not_applicable else None)
        if reason_code:
            cmp["reason_code"] = reason_code
        notable = [row for row in rows if row["materiality"] == "notable"]
        rank_magnitude = {"high": 3, "medium": 2, "low": 1}
        notable.sort(
            key=lambda row: (
                -rank_magnitude[magnitude(row)],
                -(abs(Decimal(str(row["absGap"]))) / Decimal(str(row.get("thresholdAbs") or row.get("thresholdPct")))),
                row["metric"],
            )
        )
        perf = next((row for row in rows if row["direction"] != "neutral"), None)
        price = next((row for row in rows if row["direction"] == "neutral"), None)
        chart_hints = []
        if perf:
            chart_hints.append({
                "chartType": "bar", "purpose": f"{LABELS[perf['metric']][0]} của {subject.unit_code} so với {outcome.peer_count} căn tương đồng",
                "x": "entityCode", "y": perf["metric"], "highlightEntityId": subject.unit_id,
            })
        if perf and price:
            chart_hints.append({
                "chartType": "scatter", "purpose": f"{LABELS[price['metric']][0]} và {LABELS[perf['metric']][0]} trong nhóm tương đồng",
                "x": price["metric"], "y": perf["metric"], "highlightEntityId": subject.unit_id,
            })
        cmp.update({
            "peerDefinitionRef": pd["artifact_id"], "comparisonMode": "peer_group",
            "metrics": rows,
            "notableDifferences": [
                {"metric": row["metric"], "statement": _statement(subject.unit_code, row),
                 "magnitude": magnitude(row), "evidenceRef": row["computationId"]}
                for row in notable
            ],
            "chartHints": chart_hints,
            "confidence": confidence(outcome.peer_count, min_n, outcome.relaxation["isPeerSampleConstrained"], status == "PARTIAL"),
            "usedDefaults": (
                ([] if raw.get("comparisonMode") else ["comparisonMode=peer_group"]) +
                ([] if raw.get("metricsRequested") else ["metrics=" + ",".join(DEFAULT_METRICS)])
            ),
        })
        cmp["dataSufficiency"] = sufficiency
        if insufficient:
            cmp["suggestedNextSteps"] = _next_steps(subject, group)
        if perf:
            cmp["ranking"] = {
                "basis": perf["metric"], "rankInPeerGroup": perf["rankInGroup"],
                "of": perf["groupSize"], "percentile": perf["percentileRank"],
            }
        if peer_ids:
            cmp["peerValues"] = [
                {
                    "entityId": unit_id, "entityCode": lookup[unit_id].unit_code,
                    "role": "subject" if i == 0 else "peer",
                    **({"similarityScore": outcome.peers[i - 1]["similarityScore"]} if i else {}),
                    "values": {metric: number(lookup[unit_id].metrics.get(metric))
                               if applies_to(metric, lookup[unit_id]) else None for metric in applicable},
                }
                for i, unit_id in enumerate([subject.unit_id, *peer_ids])
            ]
        return {"peer_definition": pd, "comparison": _seal(cmp)}
    @staticmethod
    def _cross_check(subject, pool, package, scope, area_pct, min_n, must_match, outcome) -> None:
        """Eval-only shadow run of Compare's own rule; a mismatch is logged, never applied (spec §1.5)."""
        own = build_peer_group(subject, pool, snapshot_id=package.snapshot_id, scope=scope, area_pct=area_pct,
                               min_peers=min_n, relax=True, must_match=must_match)
        only_data = sorted(outcome.qualified_ids - own.qualified_ids)
        only_compare = sorted(own.qualified_ids - outcome.qualified_ids)
        if only_data or only_compare:
            log.warning("PEER_RULE_DRIFT subject=%s only_in_peer_set=%s only_in_compare_rule=%s",
                        subject.unit_id, only_data, only_compare)

    def _base(self, package, raw, mode, status="VALID", limits=None):
        result = self._env(package, raw, "comparison", status, limits or [CAUSAL_LIMIT])
        result["schema_version"] = "comparison@1.1.0"
        result.update(comparisonMode=mode, metrics=[], notableDifferences=[],
                      chartHints=[], usedDefaults=[], confidence="none")
        return result

    def _external(self, package, raw):
        if raw["subject"].get("entityType") != "project":
            return self._invalid(package, raw, "external_benchmark", "INVALID_INPUT", "External benchmark chỉ áp dụng cho dự án.")
        _, error = self._group(package, raw["subject"], _scope(raw))
        if error:
            return self._invalid(package, raw, "external_benchmark", error, "Không xem được dự án.")
        result = self._base(package, raw, "external_benchmark", "PARTIAL", [
            "Chưa có dữ liệu thị trường để so sánh.", CAUSAL_LIMIT])
        result.update(reason_code="INSUFFICIENT_EVIDENCE", reason=MARKET_REASON,
                      suggestedNextStep=MARKET_NEXT_STEP)
        return {"peer_definition": None, "comparison": _seal(result)}

    def _group(self, package, ref, scope):
        level = ref.get("entityType")
        key = ref.get("entityId") or ref.get("entityCode")
        if level not in {"project", "zone"}:
            return [], "INVALID_INPUT"
        all_units = [u for u in package.units
                     if (u.project_id if level == "project" else u.zone_id) == key]
        if not all_units:
            return [], "SUBJECT_NOT_FOUND"
        allowed = [u for u in all_units if package.in_scope(u, scope)]
        return allowed, None if allowed else "PERMISSION_DENIED"

    def _requested(self, raw, mode):
        metrics = list(raw.get("metricsRequested") or DEFAULT_METRICS)
        supported = set(SOURCES) | ({"absorption_rate"} if mode == "head_to_head" else set())
        if not metrics or len(metrics) != len(set(metrics)) or any(m not in supported for m in metrics):
            return [], "Chỉ số không hợp lệ hoặc không có dữ liệu nguồn."
        if mode == "ranking" and len(metrics) != 1:
            return [], "Ranking cần đúng một chỉ số."
        return metrics, None

    def _gap(self, a, b, metric):
        delta = rounded(a - b)
        pct = rounded((a - b) / b * 100) if b else None
        kind, limit = threshold(metric)
        exceeded = abs(delta) >= limit if kind == "abs" else pct is not None and abs(pct) >= limit
        direction = DIRECTIONS[metric]
        if direction == "neutral":
            position = "higher" if delta > 0 else "lower" if delta < 0 else "inline"
        elif not exceeded:
            position = "inline"
        else:
            better = delta > 0 if direction == "higher_is_better" else delta < 0
            position = "better" if better else "worse"
        return {"absGap": number(delta), "pctGap": number(pct), "position": position,
                "thresholdAbs" if kind == "abs" else "thresholdPct": number(limit)}

    def _head_to_head(self, package, raw, scope):
        targets = raw.get("targets") or []
        if len(targets) != 1 or not isinstance(targets[0], dict):
            return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Cần đúng một target.")
        left, right = raw["subject"], targets[0]
        level = left.get("entityType", "unit")
        if right.get("entityType", "unit") != level:
            return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Hai đối tượng phải cùng cấp.")
        metrics, error = self._requested(raw, "head_to_head")
        if error:
            return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", error)
        if level == "unit":
            a, error, _ = package.resolve_unit(left, scope)
            if error:
                return self._invalid(package, raw, "head_to_head", error, "Không xem được subject.")
            b, error, _ = package.resolve_unit(right, scope)
            if error:
                return self._invalid(package, raw, "head_to_head", error, "Không xem được target.")
            if a.unit_id == b.unit_id:
                return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Hai căn phải khác nhau.")
            mismatch = [label for ok, label in (
                (a.project_id == b.project_id, "khác dự án"),
                (b.unit_type == a.unit_type, "khác loại căn"),
                (b.launch_batch_id == a.launch_batch_id, "khác đợt"),
                (abs(b.area_m2 - a.area_m2) <= a.area_m2 / 10, "lệch diện tích quá 10%"),
                (ORIENTATION_GROUP.get(b.balcony_orientation) == ORIENTATION_GROUP.get(a.balcony_orientation), "khác nhóm hướng"),
                (b.floor_band == a.floor_band, "khác nhóm tầng"),
                (b.status == "available", "căn đích không còn mở bán"),
            ) if not ok]
            peer_match = not mismatch
            groups = ([a], [b])
            limits = ["So sánh 2 căn: không đại diện cho nhóm."]
            if mismatch:
                limits.append(f"Hai căn không tương đồng theo luật peer ({', '.join(mismatch)}).")
        elif level in {"zone", "project"}:
            a, error = self._group(package, left, scope)
            if error:
                return self._invalid(package, raw, "head_to_head", error, "Không xem được subject.")
            b, error = self._group(package, right, scope)
            if error:
                return self._invalid(package, raw, "head_to_head", error, "Không xem được target.")
            if (left.get("entityId") or left.get("entityCode")) == (right.get("entityId") or right.get("entityCode")):
                return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Hai nhóm phải khác nhau.")
            if level == "zone" and a[0].project_id != b[0].project_id:
                return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Hai phân khu phải cùng dự án.")
            types = sorted({u.unit_type for u in [*a, *b]})
            unit_type = raw.get("unitTypeFilter")
            if len(types) > 1 and not unit_type:
                return self._invalid(package, raw, "head_to_head", "CLARIFICATION_NEEDED",
                                     "Cần chọn loại căn.", {"question": TYPE_QUESTION,
                                     "options": [{"entityId": t} for t in types]})
            unit_type = unit_type or types[0]
            if unit_type not in types:
                return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Loại căn không có.")
            groups = ([u for u in a if u.unit_type == unit_type],
                      [u for u in b if u.unit_type == unit_type])
            peer_match, limits = None, []
        else:
            return self._invalid(package, raw, "head_to_head", "INVALID_INPUT", "Cấp đối tượng không hỗ trợ.")
        min_n = int(package.approved_config.get("min_peer_count", "5"))
        rows, dropped, counts = [], [], []
        not_applicable = [m for m in metrics if level == "unit" and m in GROUP_ONLY]
        for metric in [m for m in metrics if m not in not_applicable]:
            def value(units, metric=metric):
                if metric == "absorption_rate":
                    n = len(units)
                    return (rounded(Decimal(sum(u.status == "sold" for u in units)) / n * 100), n) if n >= min_n else (None, n)
                values = [u.metrics.get(metric) for u in units if level == "unit" or u.status == "available"]
                values = [v for v in values if v is not None]
                if level == "unit":
                    return (values[0], 1) if values else (None, 0)
                bm = benchmark(values, min_n)
                return (Decimal(str(bm["value"])), len(values)) if bm else (None, len(values))
            va, na = value(groups[0])
            vb, nb = value(groups[1])
            if va is None or vb is None:
                dropped.append(metric)
                continue
            gap = self._gap(va, vb, metric)
            row = {"metric": metric, "unit": "percent" if metric == "absorption_rate" else UNITS[metric],
                   "direction": DIRECTIONS[metric], "subjectValue": number(va), "targetValue": number(vb),
                   **gap, "computationId": f"h2h_{metric}@{package.metric_artifact_id}"}
            if level != "unit":
                kind, limit = threshold(metric)
                exceeds = abs(Decimal(str(gap["absGap"]))) >= limit if kind == "abs" else (
                    gap["pctGap"] is not None and abs(Decimal(str(gap["pctGap"]))) >= limit)
                row.update(subjectN=na, targetN=nb, materiality="notable" if exceeds else "minor")
            rows.append(row)
            counts.append(min(na, nb))
        status = "PARTIAL" if dropped or not_applicable or not rows else "VALID"
        limits += [f"Bỏ chỉ số {m}: thiếu dữ liệu một bên." if level == "unit"
                   else f"Bỏ chỉ số {m}: một bên có dưới {min_n} căn có dữ liệu." for m in dropped]
        limits += [f"Bỏ chỉ số {m}: chỉ có nghĩa ở cấp nhóm, không áp dụng cho một căn." for m in not_applicable]
        limits.append(CAUSAL_LIMIT)
        result = self._base(package, raw, "head_to_head", status, limits)
        h2h = {"level": "unit" if level == "unit" else "group", "target": dict(right), "rows": rows}
        if level == "unit":
            h2h["peerRuleMatch"] = peer_match
        else:
            h2h["unitTypeFilter"] = unit_type
        result["headToHead"] = h2h
        source_tables = {SOURCES[m][0] for m in metrics if m in SOURCES}
        if "absorption_rate" in metrics:
            source_tables.add("fact_unit_inventory_snapshot")
        result["source_refs"] = sorted(source_tables)
        result["evidence_refs"] = [r["computationId"] for r in rows]
        result["confidence"] = ("none" if not rows else "low" if level == "unit" or status == "PARTIAL"
                                else confidence(min(counts), min_n))
        if not rows:
            result.update(reason_code="INSUFFICIENT_EVIDENCE", reason="Không đủ dữ liệu cho cả hai bên.")
        elif not_applicable:
            result["reason_code"] = "METRIC_NOT_APPLICABLE"
        result["chartHints"] = [{"chartType": "bar", "purpose": "So trực diện hai đối tượng",
                                "x": "entityCode", "y": m} for m in metrics if m not in dropped]
        return {"peer_definition": None, "comparison": _seal(result)}
    def _population(self, package, raw, scope, mode):
        ref = raw["subject"]
        level = ref.get("entityType", "unit")
        unit = None
        if level == "unit":
            unit, error, _ = package.resolve_unit(ref, scope)
            if error:
                return [], None, error
            population = [u for u in package.units if u.project_id == unit.project_id and package.in_scope(u, scope)]
        else:
            population, error = self._group(package, ref, scope)
            if error:
                return [], None, error
        population = [u for u in population if u.status == "available"]
        types = sorted({u.unit_type for u in population})
        unit_type = raw.get("unitTypeFilter")
        if mode == "cohort" and len(types) > 1 and not unit_type:
            return population, None, "CLARIFICATION_NEEDED"
        if unit_type:
            if unit_type not in types:
                return [], None, "INVALID_INPUT"
            population = [u for u in population if u.unit_type == unit_type]
        elif len(types) == 1:
            unit_type = types[0]
        return population, unit, None

    def _cohort(self, package, raw, scope):
        dimension = raw.get("cohortDimension")
        if dimension not in VALID_DIMENSIONS:
            return self._invalid(package, raw, "cohort", "INVALID_INPUT", "Cần chiều chia nhóm hợp lệ.")
        metrics, error = self._requested(raw, "cohort")
        if error:
            return self._invalid(package, raw, "cohort", "INVALID_INPUT", error)
        population, _, error = self._population(package, raw, scope, "cohort")
        if error:
            if error == "CLARIFICATION_NEEDED":
                types = sorted({u.unit_type for u in population})
                return self._invalid(package, raw, "cohort", error, "Cần chọn loại căn.",
                                     {"question": TYPE_QUESTION,
                                      "options": [{"entityId": t} for t in types[:10]]})
            return self._invalid(package, raw, "cohort", error, "Phạm vi hoặc loại căn không hợp lệ.")
        min_n = int(package.approved_config.get("min_peer_count", "5"))
        unit_type = raw.get("unitTypeFilter") or population[0].unit_type if population else ""
        def group_key(unit):
            if dimension == "orientation_group":
                return ORIENTATION_GROUP[unit.balcony_orientation]
            if dimension == "area_band":
                area = unit.area_m2
                return "<50" if area < 50 else "50–70" if area < 70 else "70–90" if area < 90 else "≥90"
            return str(unit.attribute(dimension))
        grouped = defaultdict(list)
        for unit in population:
            grouped[group_key(unit)].append(unit)
        overall = {m: bm for m in metrics
                   if (bm := benchmark([u.metrics.get(m) for u in population], min_n))}
        group_rows, skipped = [], []
        ordered_keys = sorted(grouped, key=lambda key: FLOOR_BANDS.index(key) if dimension == "floor_band" else key)
        for key in ordered_keys:
            units = grouped[key]
            entries = []
            for metric in metrics:
                bm = benchmark([u.metrics.get(metric) for u in units], min_n)
                if bm and metric in overall:
                    gap = self._gap(Decimal(str(bm["value"])), Decimal(str(overall[metric]["value"])), metric)
                    kind, limit = threshold(metric)
                    exceeds = abs(Decimal(str(gap["absGap"]))) >= limit if kind == "abs" else (
                        gap["pctGap"] is not None and abs(Decimal(str(gap["pctGap"]))) >= limit)
                    entries.append({"metric": metric, "benchmark": bm, "absGap": gap["absGap"],
                                    "pctGap": gap["pctGap"], "position": gap["position"],
                                    "materiality": "notable" if exceeds else "minor"})
            if entries:
                group_rows.append({"key": key, "metrics": entries})
            else:
                skipped.append({"key": key, "n": len(units)})
        skipped_lines = [f"Nhóm {row['key']} chỉ có {row['n']} căn (<{min_n}), không tính." for row in skipped]
        if len(group_rows) < 2:
            result = self._base(package, raw, "cohort", "PARTIAL", [
                *skipped_lines, "Không đủ 2 nhóm có dữ liệu để so sánh.", CAUSAL_LIMIT])
            result.update(reason_code="INSUFFICIENT_EVIDENCE",
                          cohorts={"dimension": dimension, "unitTypeFilter": unit_type, "overall": {},
                                   "groups": [], "skippedGroups": skipped})
            return {"peer_definition": None, "comparison": _seal(result)}
        for metric in metrics:
            candidates = [(row["key"], entry) for row in group_rows for entry in row["metrics"]
                          if entry["metric"] == metric]
            direction = DIRECTIONS[metric]
            reverse = direction == "higher_is_better"
            ordered = sorted(candidates, key=lambda item: Decimal(str(item[1]["benchmark"]["value"])), reverse=reverse)
            values = [Decimal(str(entry["benchmark"]["value"])) for _, entry in ordered]
            for _, entry in ordered:
                value = Decimal(str(entry["benchmark"]["value"]))
                entry["rank"] = 1 + sum(v > value if reverse else v < value for v in values)
                entry["of"] = len(ordered)
        limits = [*skipped_lines, CAUSAL_LIMIT]
        status = "PARTIAL" if skipped else "VALID"
        result = self._base(package, raw, "cohort", status, limits)
        result["cohorts"] = {"dimension": dimension, "unitTypeFilter": unit_type,
                             "overall": overall, "groups": group_rows, "skippedGroups": skipped}
        result["confidence"] = confidence(min(entry["benchmark"]["n"] for row in group_rows
                                               for entry in row["metrics"]), min_n, partial=status == "PARTIAL")
        result["source_refs"] = sorted({SOURCES[m][0] for m in overall})
        result["evidence_refs"] = [f"cohort_{m}@{package.metric_artifact_id}" for m in overall]
        result["chartHints"] = [{"chartType": "bar", "purpose": f"So nhóm theo {dimension}",
                                "x": dimension, "y": m} for m in overall]
        return {"peer_definition": None, "comparison": _seal(result)}

    def _ranking(self, package, raw, scope):
        metrics, error = self._requested(raw, "ranking")
        if error:
            return self._invalid(package, raw, "ranking", "INVALID_INPUT", error)
        population, subject, error = self._population(package, raw, scope, "ranking")
        if error:
            return self._invalid(package, raw, "ranking", error, "Phạm vi hoặc loại căn không hợp lệ.")
        metric = metrics[0]
        units = [u for u in population if u.metrics.get(metric) is not None]
        min_n = int(package.approved_config.get("min_peer_count", "5"))
        bm = benchmark([u.metrics[metric] for u in units], min_n)
        if not bm:
            result = self._base(package, raw, "ranking", "PARTIAL", [
                f"Chỉ có {len(units)} căn có {metric} (<{min_n}); không xếp hạng.", CAUSAL_LIMIT])
            result.update(reason_code="INSUFFICIENT_EVIDENCE")
            return {"peer_definition": None, "comparison": _seal(result)}
        options = raw.get("rankingOptions") or {}
        # Orchestrator contract v1.0.0 names: attention_first | best_first ("attention" = v5.2 alias).
        order = {"attention": "attention_first"}.get(options.get("order"), options.get("order", "attention_first"))
        try:
            top_n = int(options.get("topN", 20))
        except (ValueError, TypeError):
            top_n = 0
        if order not in {"attention_first", "best_first"} or not 1 <= top_n <= 100:
            return self._invalid(package, raw, "ranking", "INVALID_INPUT", "rankingOptions không hợp lệ.")
        direction = DIRECTIONS[metric]
        reverse_best = direction == "higher_is_better"
        values = [u.metrics[metric] for u in units]
        def rank(unit):
            value = unit.metrics[metric]
            return 1 + sum(v > value if reverse_best else v < value for v in values)
        best_first = order == "best_first"
        displayed = sorted(units, key=lambda u: (-(u.metrics[metric]) if reverse_best == best_first
                                                  else u.metrics[metric], u.unit_code))
        # attention reverses the numeric ordering used for best rank
        rows = [{"rank": rank(u), "entityId": u.unit_id, "entityCode": u.unit_code,
                 "value": number(u.metrics[metric])} for u in displayed[:top_n]]
        ranking = {"basis": metric, "direction": direction, "order": order,
                   "distribution": bm, "rows": rows}
        if subject and subject in units:
            value = subject.metrics[metric]
            ranking["subjectPosition"] = {"entityId": subject.unit_id, "entityCode": subject.unit_code,
                                          "value": number(value), "rank": rank(subject), "of": len(units),
                                          "percentile": number(rounded(Decimal(100) *
                                                                      sum(v <= value for v in values) / len(values)))}
        result = self._base(package, raw, "ranking")
        result["rankingList"] = ranking
        result["confidence"] = confidence(len(units), min_n)
        result["source_refs"] = [SOURCES[metric][0]]
        result["evidence_refs"] = [f"ranking_{metric}@{package.metric_artifact_id}"]
        result["chartHints"] = [{"chartType": "bar", "purpose": f"Xếp hạng theo {metric}",
                                "x": "entityCode", "y": metric}]
        return {"peer_definition": None, "comparison": _seal(result)}
