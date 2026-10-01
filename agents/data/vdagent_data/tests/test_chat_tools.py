"""The explanation chat reads what Data stored (dataset / metric / dq) and nothing else.

Packages are loaded through the Backend's real artifact tools; every expected value is computed here with independent SQL on
the mock DW. The tools are read-only: no warehouse query and no artifact write happens while the chat answers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from vdagent_data.chat.packages import Packages, load_latest
from vdagent_data.chat.tools import ChatTools
from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import McpPort
from vdagent_data.tests.test_steps import step
from vdagent_data.tests.test_v1_steps import ent, truth, v1
from vdagent_data.v1 import V1Result, run_step_v1

UNIT_ROW = ("SELECT i.inventory_status, i.unsold_days_dom, i.net_price_per_m2 FROM dim_unit_master u"
            " JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key AND i.snapshot_date_key = 20260928 WHERE u.unit_code = ?")
ZONE_UNITS = ("SELECT COUNT(*) FROM dim_unit_master u JOIN dim_zone_master z ON z.zone_key = u.zone_key"
              " JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key AND i.snapshot_date_key = 20260928 WHERE z.zone_name = ?")


async def fetched(port: McpPort, operation: str, spec: dict[str, Any], question: str = "câu hỏi") -> V1Result:
    r = await run_step_v1(v1(operation, spec, question=question), port)
    assert r.report.state == "completed", r.report.error
    return r


async def chat_tools(port: McpPort) -> ChatTools:
    packages = await load_latest(port)
    assert packages is not None
    return ChatTools(packages)


# ---- loading ---------------------------------------------------------------------------------------------------------------


async def test_nothing_is_loaded_before_data_has_fetched_something(alice: McpPort) -> None:
    assert await load_latest(alice) is None


async def test_the_newest_dataset_is_loaded_with_its_own_metric_and_dq(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]})
    second = await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]}, "Vì sao căn A12-08 bán chậm?")
    packages = await load_latest(alice)
    assert isinstance(packages, Packages)
    refs = {r.artifact_type.value: r for r in second.report.artifact_refs}
    assert packages.dataset["artifact_id"] == refs["dataset"].artifact_id
    assert packages.metric is not None and packages.metric["artifact_id"] == refs["metric"].artifact_id
    assert packages.dq is not None and packages.dq["artifact_id"] == refs["dq"].artifact_id


async def test_another_users_packages_are_not_loaded(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    assert await load_latest(alice.as_user("u_000000000002")) is None


async def test_loading_only_reads(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    before = len(alice.calls)
    await load_latest(alice)
    assert set(alice.calls[before:]) <= {"artifact_list", "artifact_get"}


# ---- the tools -------------------------------------------------------------------------------------------------------------


async def test_the_overview_says_what_was_fetched(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]}, "Tình hình phân khu Tòa Aqua 1?")
    out = (await chat_tools(alice)).run("get_overview", {})
    assert out["snapshot_id"] == "SNAP-2026-09-28" and out["semantic_config_version"] == "sc-1"
    assert out["operation"] == "fetch_units" and out["original_question"] == "Tình hình phân khu Tòa Aqua 1?"
    assert out["row_counts"]["dim_unit_master"] == truth(re_db, ZONE_UNITS, "Tòa Aqua 1")[0][0]
    assert out["data_quality_status"] in ("VALID", "PARTIAL")


async def test_the_resolution_tells_how_the_entity_was_matched(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("a12 08")]}, "Vì sao căn a12 08 bán chậm?")
    out = (await chat_tools(alice)).run("get_resolution", {})
    [entity] = out["entities"]
    assert (entity["mention"], entity["kind"], entity["name"]) == ("a12 08", "UNIT", "A12-08")
    assert entity["how"] and "chuẩn hóa" in entity["how"]
    assert out["original_question"] == "Vì sao căn a12 08 bán chậm?" and out["scope_all"] is False


async def test_a_unit_is_found_by_any_spelling_and_matches_the_warehouse(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("get_unit", {"unit_code": "a12 08"})
    assert out["found"] is True and out["unit"]["unit_code"] == "A12-08"
    [(status, dom, price)] = truth(re_db, UNIT_ROW, "A12-08")
    assert out["inventory"]["inventory_status"] == status
    assert Decimal(str(out["inventory"]["unsold_days_dom"])) == Decimal(str(dom))
    assert Decimal(str(out["inventory"]["net_price_per_m2"])) == Decimal(str(price))


async def test_the_key_figures_of_a_unit_say_what_each_one_is(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("get_unit", {})
    figures = {f["name"]: f for f in out["key_figures"]}
    [(status, dom, price)] = truth(re_db, UNIT_ROW, "A12-08")
    assert Decimal(str(figures["unsold_days_dom"]["value"])) == Decimal(str(dom))
    assert Decimal(str(figures["net_price_per_m2"]["value"])) == Decimal(str(price))
    assert figures["inventory_status"]["value"] == status
    assert all(f["meaning"] for f in figures.values())
    assert "giá đất" not in " ".join(f["meaning"] for f in figures.values())
    assert "gộp" in figures["area_m2"]["meaning"] and "ròng" in figures["net_area_m2"]["meaning"]  # the two areas are told apart


async def test_a_figure_the_package_lacks_is_left_out_not_invented(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    packages = await load_latest(alice)
    assert packages is not None
    tables = packages.dataset["payload"]["tables"]
    stripped = {**tables, "fact_unit_inventory_snapshot": [{k: v for k, v in r.items() if k != "asking_price_vnd"}
                                                           for r in tables["fact_unit_inventory_snapshot"]]}
    patched = Packages({**packages.dataset, "payload": {**packages.dataset["payload"], "tables": stripped}}, packages.metric, packages.dq)
    assert "asking_price_vnd" not in {f["name"] for f in ChatTools(patched).run("get_unit", {})["key_figures"]}


async def test_this_unit_means_the_only_unit_of_the_package(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("get_unit", {})
    assert out["found"] is True and out["unit"]["unit_code"] == "A12-08"


async def fetched_with_candidates(port: McpPort) -> None:
    """What the Orchestrator asks for today: the unit and every candidate peer of its type in one package."""
    report = await run_step(step(spec={"subject_unit_code": "A12-08", "population": "peer_candidates"}), port)
    assert report.state == "completed", report.error


async def test_this_unit_is_the_subject_even_when_the_package_holds_its_candidates(alice: McpPort) -> None:
    await fetched_with_candidates(alice)
    tools = await chat_tools(alice)
    assert tools.run("get_overview", {})["row_counts"]["dim_unit_master"] > 1
    out = tools.run("get_unit", {})
    assert out["found"] is True and out["unit"]["unit_code"] == "A12-08"
    assert tools.run("get_overview", {})["subject_unit"] == "A12-08"


async def test_the_resolution_explains_why_the_package_holds_many_units(alice: McpPort) -> None:
    await fetched_with_candidates(alice)
    out = (await chat_tools(alice)).run("get_resolution", {})
    assert out["population"]["rule"] == "peer_candidates" and "ứng viên" in out["population"]["meaning"]


async def test_without_a_code_a_package_of_many_units_asks_for_one(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]})
    out = (await chat_tools(alice)).run("get_unit", {})
    assert out["found"] is False and out["units_in_package"] > 1 and "mã căn" in out["reason"]


async def test_a_unit_that_was_not_fetched_is_not_found_and_the_warehouse_is_not_asked(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    tools = await chat_tools(alice)
    before = len(alice.calls)
    out = tools.run("get_unit", {"unit_code": "A12-11"})  # a real unit of the same project, but not in this package
    assert out["found"] is False and out["units_in_package"] == 1
    assert len(alice.calls) == before


async def test_listing_units_is_paged(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]})
    tools = await chat_tools(alice)
    total = truth(re_db, ZONE_UNITS, "Tòa Aqua 1")[0][0]
    first = tools.run("list_units", {"limit": 2})
    assert first["total"] == total and len(first["units"]) == min(2, total)
    rest = tools.run("list_units", {"limit": 2, "offset": 2})
    assert {u["unit_code"] for u in first["units"]}.isdisjoint(u["unit_code"] for u in rest["units"])
    assert len(tools.run("list_units", {"limit": 10_000})["units"]) <= 50  # capped


async def test_metrics_are_passed_on_as_computed(alice: McpPort) -> None:
    await fetched(alice, "aggregate_metrics", {"entities": [ent("Tòa Aqua 1", "ZONE")], "metrics": ["unit_count", "avg_dom_unsold"]})
    out = (await chat_tools(alice)).run("get_metrics", {})
    by_id = {m["metric_id"]: m for m in out["metrics"]}
    assert set(by_id) == {"unit_count", "avg_dom_unsold"}
    assert by_id["avg_dom_unsold"]["unit"] == "DAY" and by_id["avg_dom_unsold"]["n"] >= 1


async def test_missing_values_are_listed_with_a_reason_and_never_filled(alice: McpPort) -> None:
    r = await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("get_missing", {})
    raw = {item["details"]["raw"] for item in out["limitations"]}
    assert {w for w in r.report.warnings if w.startswith(("METRIC_UNAVAILABLE", "WINDOW_INCOMPLETE", "DQ_MISSING"))} <= raw
    assert all(item["message"] for item in out["limitations"])
    unavailable = [i for i in out["limitations"] if i["details"]["raw"].startswith("METRIC_UNAVAILABLE")]
    # Data only knows it could not read the column through the standard read layer; it must not claim the warehouse lacks it
    assert unavailable and all("không đọc được" in i["message"] and "Kho dữ liệu không có" not in i["message"] for i in unavailable)
    assert all("Kho dữ liệu không có" not in m["reason"] for m in out["metrics_without_value"])
    assert all(m["value"] is None for m in out["metrics_without_value"])
    assert out["metrics_without_value"] and all(m["meaning"] for m in out["metrics_without_value"])  # what the metric is, from the glossary


async def test_excluded_units_are_reported_with_their_reason(alice: McpPort) -> None:
    packages = await load_latest(alice)
    assert packages is None  # nothing yet
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    packages = await load_latest(alice)
    assert packages is not None
    patched = Packages(dataset={**packages.dataset, "payload": {**packages.dataset["payload"],
                                                                 "excluded": [{"unit_code": "A12-11", "reason": "net_area_unavailable"}]}},
                       metric=packages.metric, dq=packages.dq)
    out = ChatTools(patched).run("get_missing", {})
    assert out["excluded"] == [{"unit_code": "A12-11", "reason": "net_area_unavailable"}]


async def test_the_sources_name_the_tables_the_snapshot_and_the_thresholds(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("get_sources", {})
    assert {q["table"] for q in out["queries"]} >= {"dim_unit_master", "fact_unit_inventory_snapshot"}
    assert all(len(q["sql_sha256"]) == 64 for q in out["queries"]) and out["snapshot_id"] == "SNAP-2026-09-28"
    assert all({"value", "status"} <= set(v) for v in out["thresholds"].values())


@pytest.mark.parametrize("term,kind", [("avg_dom_unsold", "metric"), ("slow_moving", "filter"), ("METRIC_UNAVAILABLE", "limitation"),
                                       ("normalized", "match_method")])
async def test_a_term_is_defined_from_the_agents_own_vocabulary(alice: McpPort, term: str, kind: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    out = (await chat_tools(alice)).run("define_term", {"term": term})
    assert out["found"] is True and kind in {m["kind"] for m in out["matches"]}
    assert all(m["meaning"] for m in out["matches"])


def test_every_metric_filter_and_attribute_name_of_the_vocabulary_can_be_defined() -> None:
    """Ratchet: a name added to `vocab.py` without a meaning in `glossary.py` fails here, not in front of a user."""
    from vdagent_data import steps, vocab
    from vdagent_data.chat.glossary import define

    for name in (*vocab.METRICS_V1, *vocab.FILTERS, *steps.UNIT_METRICS):  # UNIT_METRICS: the names of the single-unit path
        assert define(name, {})["found"] is True, name


async def test_an_unknown_term_is_not_invented(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    assert (await chat_tools(alice)).run("define_term", {"term": "zzz không tồn tại"}) == {"found": False, "matches": []}


async def test_a_threshold_is_quoted_from_the_package_not_from_code(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    tools = await chat_tools(alice)
    thresholds = tools.run("get_sources", {})["thresholds"]
    assert "overdue_threshold_days" in thresholds
    out = tools.run("define_term", {"term": "slow_moving"})
    assert str(thresholds["overdue_threshold_days"]["value"]) in out["matches"][0]["meaning"]


async def test_bad_calls_are_answered_not_raised(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    tools = await chat_tools(alice)
    assert "error" in tools.run("drop_everything", {})
    assert "error" in tools.run("get_unit", {"unit_code": ""})
    assert "error" in tools.run("list_units", {"limit": "many"})


async def test_the_schemas_list_exactly_the_tools_that_run(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    tools = await chat_tools(alice)
    names = [s["function"]["name"] for s in tools.schemas()]
    assert names == sorted(set(names), key=names.index) and len(names) == 8
    for name in names:
        assert "error" not in tools.run(name, {"unit_code": "A12-08", "term": "dom_days"}), name
