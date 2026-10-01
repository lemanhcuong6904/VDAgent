"""The read-only tools of the explanation chat, over one `Packages` already in memory.

Each tool answers from what Data stored and nothing else: no warehouse query, no artifact write, no I/O. A value that is
missing stays `None` with its reason; a unit that is not in the package is "not found", not looked up. A bad call is answered
with `{"error": ...}` so the model can correct itself; nothing here raises into the turn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vdagent_data.chat import glossary
from vdagent_data.chat.packages import Packages
from vdagent_data.resolve import unit_code_form
from vdagent_data.wire import map_warning

DEFAULT_LIST = 20
MAX_LIST = 50
_UNIT_TABLES = ("dim_unit_master", "unit_inventory")  # a fetch writes the first; an aggregate writes the second
_LIST_FIELDS = ("unit_code", "inventory_status", "unsold_days_dom", "net_price_per_m2", "asking_price_vnd", "zone_key", "project_key")


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NoArgs(_Args):
    pass


class UnitArgs(_Args):
    unit_code: str | None = Field(default=None, min_length=1, max_length=40,
                                  description="Mã căn, viết kiểu nào cũng được (A12-08, a12 08). Bỏ trống nếu gói chỉ có một căn (\"căn này\").")


class ListArgs(_Args):
    limit: int = Field(default=DEFAULT_LIST, ge=1, description=f"Số căn tối đa, không quá {MAX_LIST}.")
    offset: int = Field(default=0, ge=0)


class TermArgs(_Args):
    term: str = Field(min_length=1, max_length=80, description="Thuật ngữ cần giải nghĩa: tên chỉ số, bộ lọc, mã hạn chế, ngưỡng.")


def _rows(packages: Packages, table: str) -> list[dict[str, Any]]:
    return list(packages.payload.get("tables", {}).get(table) or [])


def _units(packages: Packages) -> list[dict[str, Any]]:
    for table in _UNIT_TABLES:
        if rows := _rows(packages, table):
            return rows
    return []


def _by_key(rows: list[dict[str, Any]], key: str, value: Any) -> list[dict[str, Any]]:
    return [r for r in rows if r.get(key) == value]


def _config(packages: Packages) -> dict[str, Any]:
    return packages.payload.get("semantic_config") or {}


def _subject(packages: Packages) -> dict[str, Any] | None:
    """The unit the request was about ("căn này"): the one the dataset names as its subject, else the one unit entity resolved."""
    key = (packages.payload.get("population") or {}).get("subject_unit_key")
    if key is None:
        entities = (packages.payload.get("request") or {}).get("resolved_entities") or []
        key = entities[0].get("id") if len(entities) == 1 and entities[0].get("kind") == "UNIT" else None
    return next((u for u in _units(packages) if key is not None and u.get("unit_key") == key), None)


class ChatTools:
    def __init__(self, packages: Packages) -> None:
        self._p = packages
        self._tools: dict[str, tuple[str, type[_Args], Callable[[Any], dict[str, Any]]]] = {
            "get_overview": ("Tổng quan gói dữ liệu vừa lấy: câu hỏi gốc, operation, kỳ chốt, số dòng mỗi bảng, chất lượng, các hạn chế.",
                             NoArgs, self._overview),
            "get_resolution": ("Vì sao có đối tượng này: từ người dùng viết, đối tượng được nhận diện và cách khớp, phạm vi và bộ lọc.",
                               NoArgs, self._resolution),
            "get_unit": ("Thông tin đầy đủ của một căn có trong gói: căn, tồn kho, chẩn đoán, nguyên nhân, phân khu, dự án, kênh bán.",
                         UnitArgs, self._unit),
            "list_units": ("Liệt kê các căn có trong gói (phân trang): mã, trạng thái, số ngày tồn, giá.", ListArgs, self._list_units),
            "get_metrics": ("Các chỉ số Data đã tính cho gói này: giá trị, mẫu, đơn vị.", NoArgs, self._metrics),
            "get_missing": ("Dữ liệu còn thiếu: trường thiếu, chỉ số không có giá trị kèm lý do, căn bị loại, hạn chế.", NoArgs, self._missing),
            "get_sources": ("Nguồn của gói: các bảng đã đọc, số dòng, mã băm SQL, kỳ chốt, các ngưỡng nghiệp vụ và trạng thái duyệt.",
                            NoArgs, self._sources),
            "define_term": ("Giải nghĩa một thuật ngữ trong dữ liệu (chỉ số, bộ lọc, mã hạn chế, ngưỡng, cách khớp).", TermArgs, self._define),
        }

    def schemas(self) -> list[dict[str, Any]]:
        """OpenAI tool schemas of every tool."""
        return [{"type": "function", "function": {"name": name, "description": description, "parameters": model.model_json_schema()}}
                for name, (description, model, _) in self._tools.items()]

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            return {"error": f"unknown tool {name!r}"}
        _, model, handler = entry
        try:
            return handler(model.model_validate(args))
        except ValidationError as exc:
            first = exc.errors()[0]
            return {"error": f"invalid arguments for {name}: {'.'.join(str(p) for p in first['loc']) or 'arguments'}: {first['msg']}"}

    # ---- the tools ----------------------------------------------------------------------------------------------------------

    def _overview(self, _: NoArgs) -> dict[str, Any]:
        p = self._p
        request = p.payload.get("request") or {}
        snapshot = p.payload.get("snapshot") or {}
        subject = _subject(p)
        return {
            "subject_unit": subject.get("unit_code") if subject else None,
            "snapshot_id": snapshot.get("snapshot_id"), "snapshot_date": snapshot.get("snapshot_date"),
            "semantic_config_version": snapshot.get("semantic_config_version"),
            "operation": request.get("operation"), "original_question": request.get("original_question"),
            "package_status": p.dataset["status"], "row_counts": p.payload.get("row_counts") or {},
            "data_quality_status": (p.dq or {}).get("payload", {}).get("overall_status"), "limitations": p.limitations,
        }

    def _resolution(self, _: NoArgs) -> dict[str, Any]:
        p = self._p
        request = p.payload.get("request") or {}
        population = p.payload.get("population") or {}
        entities = [{**e, "how": _method_text(e.get("method"))} for e in request.get("resolved_entities") or []]
        rule = population.get("rule")
        return {"original_question": request.get("original_question"), "operation": request.get("operation"), "entities": entities,
                "scope_all": bool(population.get("scope_all", not entities)), "filters": population.get("filters") or [],
                "attributes": population.get("attributes") or [],
                "population": {"rule": rule, "meaning": glossary.POPULATION_TEXT.get(str(rule)), "details": population}}

    def _unit(self, args: UnitArgs) -> dict[str, Any]:
        p = self._p
        units = _units(p)
        if args.unit_code is None:  # "căn này": the subject of the request, else the only unit there is
            unit = _subject(p) or (units[0] if len(units) == 1 else None)
            if unit is None:
                return {"found": False, "units_in_package": len(units), "reason": "Gói có nhiều căn hoặc không có căn nào; cần nêu mã căn."}
        else:
            wanted = unit_code_form(args.unit_code)
            unit = next((u for u in units if unit_code_form(str(u.get("unit_code", ""))) == wanted), None)
        if unit is None:
            return {"found": False, "units_in_package": len(units)}
        key = unit.get("unit_key")
        stored = next(iter(_by_key(_rows(p, "fact_unit_inventory_snapshot"), "unit_key", key)), None)
        inventory = stored or (unit if "inventory_status" in unit else None)  # an aggregate stores unit and inventory in one row
        channel_key = (inventory or {}).get("channel_key")
        rows = {"inventory": inventory or {}, "unit": unit}
        figures = [{"name": name, "value": rows[source][name], "meaning": meaning}
                   for name, source, meaning in glossary.UNIT_FIGURES if name in rows[source]]
        return {
            "found": True, "key_figures": figures, "unit": unit, "inventory": inventory,
            "diagnostics": next(iter(_by_key(_rows(p, "dm_unit_friction_diagnostics"), "unit_key", key)), None),
            "causes": _by_key(_rows(p, "unit_diagnostic_causes"), "unit_key", key),
            "zone": next(iter(_by_key(_rows(p, "dim_zone_master"), "zone_key", unit.get("zone_key"))), None),
            "project": next(iter(_by_key(_rows(p, "dim_project_profile"), "project_key", unit.get("project_key"))), None),
            "channel": next(iter(_by_key(_rows(p, "dim_sales_channel"), "channel_key", channel_key)), None) if channel_key is not None else None,
        }

    def _list_units(self, args: ListArgs) -> dict[str, Any]:
        p = self._p
        units = _units(p)
        inventory = {r["unit_key"]: r for r in _rows(p, "fact_unit_inventory_snapshot")}
        limit = min(args.limit, MAX_LIST)
        page = units[args.offset:args.offset + limit]
        merged = [{**u, **inventory.get(u.get("unit_key"), {})} for u in page]
        return {"total": len(units), "offset": args.offset, "units": [{k: m[k] for k in _LIST_FIELDS if k in m} for m in merged]}

    def _metrics(self, _: NoArgs) -> dict[str, Any]:
        rows = (self._p.metric or {}).get("payload", {}).get("metrics") or []
        keep = ("metric_id", "value", "n", "unit", "statistic", "status", "numerator", "denominator")
        metrics = [{**{k: r[k] for k in keep if k in r}, "subject": (r.get("subject") or {}).get("label")} for r in rows]
        return {"metrics": metrics} if metrics else {"metrics": [], "note": "Gói này không có chỉ số nào đã tính."}

    def _missing(self, _: NoArgs) -> dict[str, Any]:
        p = self._p
        dq = (p.dq or {}).get("payload", {})
        explained = [_explain(raw) for raw in p.limitations]
        rows = (p.metric or {}).get("payload", {}).get("metrics") or []
        without = []
        for r in rows:
            if r.get("value") is not None:
                continue
            reason = next((w["message"] for w in explained if w.get("target") == r.get("metric_id")), "Không có dòng nào có giá trị để tính.")
            without.append({"metric_id": r.get("metric_id"), "meaning": glossary.metric_meaning(str(r.get("metric_id"))),
                            "subject": (r.get("subject") or {}).get("label"), "value": None, "reason": reason})
        return {
            "fields": [f for f in dq.get("fields") or [] if f.get("missing_count")],
            "sensors_violated": [s for s in dq.get("sensors") or [] if s.get("violations")],
            "metrics_without_value": without, "excluded": p.payload.get("excluded") or [], "limitations": explained,
        }

    def _sources(self, _: NoArgs) -> dict[str, Any]:
        p = self._p
        return {
            "snapshot_id": (p.payload.get("snapshot") or {}).get("snapshot_id"), "source_refs": p.dataset.get("source_refs") or [],
            "queries": p.payload.get("queries") or [],
            "thresholds": {k: {"value": v.get("value"), "status": v.get("status")} for k, v in _config(p).items()},
        }

    def _define(self, args: TermArgs) -> dict[str, Any]:
        return glossary.define(args.term, _config(self._p))


def _method_text(method: Any) -> str | None:
    return glossary.METHOD_TEXT.get(str(method)) if method else None


def _explain(raw: str) -> dict[str, Any]:
    """A limitation code in words. For an unavailable metric Data says what it knows: it could not read the column, not that the
    warehouse lacks it (the standard read layer may hide a column that exists)."""
    explained = map_warning(raw)
    if raw.startswith("METRIC_UNAVAILABLE:"):
        explained["message"] = (f"Data không đọc được chỉ số {explained['target']} qua lớp đọc dữ liệu chuẩn nên để trống, không điền 0; "
                                "chưa chắc kho gốc không có.")
    return explained
