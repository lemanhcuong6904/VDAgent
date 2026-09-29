"""Regression tests over the copied Data pack and approved A12-08 fixture."""
from __future__ import annotations

from vdagent_compare.vh_chat import parse_request, render
from vdagent_compare.vh_service import CompareService

SERVICE = CompareService()


def call(code: str, mode: str = "peer_group", **extra):
    return SERVICE.run({"subject": {"entityType": "unit", "entityCode": code},
                        "comparisonMode": mode, **extra})


def test_hero_golden_peer_group_numbers_and_exclusions():
    result = call("A12-08")
    pd, cmp = result["peer_definition"], result["comparison"]
    assert pd["peerCount"] == 5
    assert [p["entityCode"] for p in pd["peers"]] == [
        "A12-11", "A10-02", "A14-03", "B09-05", "B11-07"]
    assert cmp["status"] == "VALID"
    metrics = {row["metric"]: row for row in cmp["metrics"]}
    price = metrics["net_asking_price_per_m2"]
    dom = metrics["dom"]
    assert (price["benchmark"]["value"], price["absGap"], price["pctGap"]) == (62_500_000, 10_000_000, 16)
    assert (dom["benchmark"]["value"], dom["absGap"], dom["pctGap"]) == (48, 90, 187.5)
    assert price["rankInGroup"] == dom["rankInGroup"] == 6
    assert len(cmp["notableDifferences"]) == 2


def test_real_csv_peer_group_has_sufficient_sample():
    result = call("ZURICH-20.022")
    assert result["peer_definition"]["peerCount"] == 10
    assert result["comparison"]["status"] == "VALID"
    assert all(row["benchmark"]["n"] == 10 for row in result["comparison"]["metrics"])


def test_head_to_head_unit_no_materiality_and_group_has_medians():
    result = call("A12-08", "head_to_head",
                  targets=[{"entityType": "unit", "entityCode": "A12-11"}])
    h = result["comparison"]["headToHead"]
    assert h["level"] == "unit" and h["peerRuleMatch"] is True
    assert h["rows"][0]["absGap"] == 11_000_000
    assert all("materiality" not in row for row in h["rows"])
    grouped = SERVICE.run({
        "subject": {"entityType": "zone", "entityCode": "ZN-SAPPHIRE1"},
        "comparisonMode": "head_to_head",
        "targets": [{"entityType": "zone", "entityCode": "ZN-SAPPHIRE2"}],
        "unitTypeFilter": "2PN",
        "metricsRequested": ["dom", "net_asking_price_per_m2", "absorption_rate"],
    })["comparison"]
    assert grouped["status"] == "VALID"
    assert len(grouped["headToHead"]["rows"]) == 3
    assert all(row["subjectN"] >= 5 and row["targetN"] >= 5
               for row in grouped["headToHead"]["rows"])


def test_cohort_and_ranking_use_full_scope():
    cohort = SERVICE.run({
        "subject": {"entityType": "project", "entityCode": "PRJ-VHOP"},
        "comparisonMode": "cohort", "cohortDimension": "floor_band",
        "unitTypeFilter": "2PN", "metricsRequested": ["dom"],
    })["comparison"]
    assert cohort["status"] == "VALID"
    assert len(cohort["cohorts"]["groups"]) >= 2
    assert [group["key"] for group in cohort["cohorts"]["groups"]] == ["LOW", "MID", "HIGH", "TOP"]
    assert all(row["benchmark"]["n"] >= 5 for group in cohort["cohorts"]["groups"]
               for row in group["metrics"])
    ranking = call("SAPPHIRE1-13.001", "ranking", metricsRequested=["dom"],
                   rankingOptions={"topN": 5})["comparison"]["rankingList"]
    assert ranking["distribution"]["n"] > 100
    assert ranking["subjectPosition"]["of"] == ranking["distribution"]["n"]
    assert len(ranking["rows"]) == 5
    assert ranking["rows"][0]["value"] >= ranking["rows"][-1]["value"]


def test_unsupported_market_and_permission_never_leak_numbers():
    market = SERVICE.run({
        "subject": {"entityType": "project", "entityCode": "PRJ-VHOP"},
        "comparisonMode": "external_benchmark",
    })["comparison"]
    assert (market["status"], market["reason_code"], market["metrics"]) == (
        "PARTIAL", "INSUFFICIENT_EVIDENCE", [])
    denied = call("ZURICH-20.022", scope={"allowedZoneIds": ["ZN-SAPPHIRE1"]})["comparison"]
    assert (denied["status"], denied["reason_code"], denied["metrics"]) == (
        "INVALID", "PERMISSION_DENIED", [])


def test_hash_is_stable_across_run_ids_and_chat_parses_vietnamese():
    a = call("A12-08", run_id="first")
    b = call("A12-08", run_id="second")
    assert a["peer_definition"]["content_hash"] == b["peer_definition"]["content_hash"]
    assert a["comparison"]["content_hash"] == b["comparison"]["content_hash"]
    request = parse_request("Xếp hạng DOM của ZURICH-20.022")
    assert request["comparisonMode"] == "ranking"
    assert "Hạng" in render(call("ZURICH-20.022"))

def test_backend_plugin_demo_mode_registers_and_answers_without_model_key():
    import asyncio
    from vdagent_compare import setup

    class API:
        def __init__(self):
            self.agent = None

        def register_agent(self, *, name, description, agent):
            assert name == "compare"
            self.agent = agent

    class Context:
        history = [{"role": "user", "content": "So sánh căn ZURICH-20.022 với các căn tương đồng"}]

        def __init__(self):
            self.reply = None

        async def emit_assistant(self, content, tool_calls=()):
            self.reply = content

    api, ctx = API(), Context()
    setup(api, {"vhop_demo": True})
    asyncio.run(api.agent.invoke(ctx))
    assert "10 căn" in ctx.reply
    assert "Hoàn tất" in ctx.reply

def test_external_requires_project_and_default_ids_do_not_collide():
    invalid = call("ZURICH-20.022", "external_benchmark")["comparison"]
    assert (invalid["status"], invalid["reason_code"]) == ("INVALID", "INVALID_INPUT")
    first = call("A12-08")["comparison"]
    second = call("A12-11")["comparison"]
    assert first["artifact_id"] != second["artifact_id"]


def test_hero_full_table_matches_golden_content_hash():
    result = SERVICE.run({
        "run_id": "gc25_run_001",
        "task_id": "gc25_task_cmp_001",
        "snapshot_id": "SNAP-20260630-01",
        "comparisonMode": "peer_group",
        "subject": {"entityType": "unit", "entityId": "U812", "entityCode": "A12-08"},
        "metricsRequested": [
            "net_asking_price_per_m2", "dom", "inquiry_leads_30d",
            "discount_pct", "subsidy_duration_mo",
        ],
        "scope": {"userId": "u_salesops_01", "allowedProjectIds": ["PRJ-X"]},
        "input_artifact_refs": {
            "metricArtifactId": "art_metric_hero",
            "dqArtifactId": "art_dq_hero",
        },
        "semantic_config_version": "1.0.0",
    })
    assert result["peer_definition"]["content_hash"] == (
        "eec7bc95823c250767cbfb093dd06df88212d28398d78535ed6cd253a25345cc")
    assert result["comparison"]["content_hash"] == (
        "dd9ccf894e9f1064f2b3ad1bcd0e4f24272f5003cc8aa3528e8eabdde8d98bdf")


def test_chat_does_not_silently_choose_wrong_mode_or_ignore_entities():
    assert parse_request("Xep hang DOM cua ZURICH-20.022")["comparisonMode"] == "ranking"
    assert parse_request("So sanh DOM 2PN theo tang trong PRJ-VHOP")["comparisonMode"] == "cohort"
    assert parse_request("So A12-08 voi A12-11 va B15-02") is None
    assert parse_request("So A12-08 voi ZN-A") is None


def test_entity_id_and_code_must_resolve_to_the_same_unit():
    result = SERVICE.run({
        "subject": {"entityType": "unit", "entityId": "U812", "entityCode": "A12-11"},
        "comparisonMode": "peer_group",
    })
    assert result["peer_definition"] is None
    assert result["comparison"]["status"] == "INVALID"
    assert result["comparison"]["reason_code"] == "INVALID_INPUT"


def test_cohort_clarification_only_lists_types_in_allowed_scope(monkeypatch):
    from dataclasses import replace
    import vdagent_compare.vh_service as service_module
    from vdagent_compare.vh_data import load_hero_package

    package = load_hero_package(SERVICE.root)
    units = tuple(replace(u, unit_type="STUDIO") if u.unit_code == "B09-05" else u
                  for u in package.units)
    monkeypatch.setattr(service_module, "load_package_for",
                        lambda ref, root=None: replace(package, units=units))
    result = SERVICE.run({
        "subject": {"entityType": "zone", "entityCode": "ZN-A"},
        "comparisonMode": "cohort",
        "cohortDimension": "floor_band",
        "scope": {"allowedZoneIds": ["ZN-A"]},
    })["comparison"]
    assert result["reason_code"] == "CLARIFICATION_NEEDED"
    assert {o["entityId"] for o in result["clarification"]["options"]} == {"2PN", "3PN"}


def test_absorption_only_comparison_cites_inventory_snapshot():
    grouped = SERVICE.run({
        "subject": {"entityType": "zone", "entityCode": "ZN-SAPPHIRE1"},
        "comparisonMode": "head_to_head",
        "targets": [{"entityType": "zone", "entityCode": "ZN-SAPPHIRE2"}],
        "unitTypeFilter": "2PN",
        "metricsRequested": ["absorption_rate"],
    })["comparison"]
    assert grouped["status"] == "VALID"
    assert "fact_unit_inventory_snapshot" in grouped["source_refs"]


def test_malformed_structured_requests_return_invalid_artifacts():
    base = {"subject": {"entityType": "unit", "entityCode": "A12-08"}}
    for extra in (
        {"scope": ["bad"]},
        {"input_artifact_refs": ["bad"]},
        {"criteriaOverride": ["bad"]},
        {"metricsRequested": [{}]},
        {"metricsRequested": "dom"},
    ):
        result = SERVICE.run({**base, **extra})
        assert result["comparison"]["status"] == "INVALID"
        assert result["comparison"]["reason_code"] == "INVALID_INPUT"


# ---- hồi quy cho các lỗi tìm được khi chạy 26 golden case (spec v5.1) ----

def test_insufficient_peer_group_has_no_misleading_dropped_metric_lines():
    # Chỉ căn cùng phân khu → 3 căn, mở tầng liền kề → 4 < 5: không kết luận, KHÔNG ghi "Bỏ metric … do chỉ có 4 peer"
    cmp = call("A12-08", criteriaOverride={"mustMatch": ["zone_id"]})["comparison"]
    assert (cmp["status"], cmp["reason_code"], cmp["metrics"], cmp["confidence"]) == (
        "PARTIAL", "INSUFFICIENT_EVIDENCE", [], "none")
    assert not any(line.startswith("Bỏ metric") for line in cmp["limitations"])
    assert "peerValues" not in cmp


def test_max_peers_config_cuts_ranked_list_and_explains_cut_units():
    full = call("ZURICH-20.022")["peer_definition"]
    cut = call("ZURICH-20.022", maxPeers=6)["peer_definition"]
    assert cut["peerCount"] == 6
    assert [p["entityCode"] for p in cut["peers"]] == [p["entityCode"] for p in full["peers"][:6]]
    assert cut["excludedSummary"].get("below_similarity_cutoff") == full["peerCount"] - 6


def test_unit_head_to_head_names_the_peer_rule_mismatch():
    cmp = call("A12-08", "head_to_head", targets=[{"entityType": "unit", "entityCode": "B15-02"}])["comparison"]
    assert cmp["headToHead"]["peerRuleMatch"] is False
    assert "Hai căn không tương đồng theo luật peer (khác nhóm tầng)." in cmp["limitations"]


def test_market_benchmark_uses_contract_field_names():
    cmp = SERVICE.run({"subject": {"entityType": "project", "entityCode": "PRJ-VHOP"},
                       "comparisonMode": "external_benchmark"})["comparison"]
    assert cmp["suggestedNextStep"].startswith("ranking hoặc head_to_head")
    assert "suggestedModes" not in cmp and cmp["reason"].startswith("Chưa có dữ liệu thị trường")


def test_prefix_clarification_counts_all_matches_but_lists_at_most_ten():
    cmp = call("ZURICH-2")["comparison"]
    assert cmp["reason_code"] == "CLARIFICATION_NEEDED"
    total = int(cmp["clarification"]["question"].split(" ")[1])
    assert total >= len(cmp["clarification"]["options"]) and len(cmp["clarification"]["options"]) <= 10


def test_chat_narrowing_reaches_engine_and_does_not_silently_ignore_filters():
    from vdagent_compare.vh_chat import answer

    request = parse_request("So sanh A12-08 chi voi cac can cung phan khu")
    assert request["comparisonMode"] == "peer_group"
    assert request["criteriaOverride"] == {"mustMatch": ["zone_id"]}
    reply = answer("So sanh A12-08 chi voi cac can cung phan khu", SERVICE)
    assert "Không đủ nhóm so sánh" in reply
    assert "4 căn" in reply
    assert parse_request("So sanh A12-08 chi voi cac can co ban cong rong") is None
    assert parse_request("So sanh A12-08 voi A12-11 cung phan khu") is None
    assert parse_request("So sanh A12-08 chi voi can cung huong")["criteriaOverride"] == {
        "mustMatch": ["balcony_orientation"]}
    assert parse_request("So sanh A12-08 dien tich +/-5%")["criteriaOverride"] == {
        "areaBandPct": 5.0}
    assert parse_request("So sánh A12-08 diện tích ±5%")["criteriaOverride"] == {
        "areaBandPct": 5.0}
    too_wide = parse_request("So sanh A12-08 dien tich +/-15%")
    assert SERVICE.run(too_wide)["comparison"]["reason_code"] == "INVALID_INPUT"


def test_chat_incentives_and_default_peer_table_are_complete():
    from vdagent_compare.vh_chat import answer

    default_request = parse_request("So sanh A12-08 voi cac can tuong dong")
    assert default_request["metricsRequested"] == [
        "net_asking_price_per_m2", "dom", "inquiry_leads_30d",
        "discount_pct", "subsidy_duration_mo",
    ]
    request = parse_request("So sanh A12-08 ve gia, DOM, luot quan tam, uu dai")
    assert request["metricsRequested"] == [
        "net_asking_price_per_m2", "dom", "inquiry_leads_30d",
        "discount_pct", "subsidy_duration_mo",
    ]
    reply = answer("So sanh A12-08 ve gia, DOM, luot quan tam, uu dai", SERVICE)
    for label in ("Giá ròng/m²", "DOM", "Lượt quan tâm 30 ngày",
                  "Chiết khấu", "Hỗ trợ lãi suất", "Điểm đáng chú ý",
                  "A12-08", "A12-11"):
        assert label in reply
    assert "| Căn |" in reply


def test_chat_partial_unit_code_returns_specific_choices():
    from vdagent_compare.vh_chat import answer

    request = parse_request("So sanh ZURICH-20")
    assert request["subject"]["entityCode"] == "ZURICH-20"
    reply = answer("So sanh ZURICH-20", SERVICE)
    assert "Cần làm rõ yêu cầu" in reply
    assert "Bạn muốn so căn nào?" in reply
    assert "ZURICH-20." in reply


def test_chat_localizes_status_confidence_and_percentile():
    from vdagent_compare.vh_chat import answer

    peer_reply = answer("So sanh ZURICH-20.022 voi cac can tuong dong", SERVICE)
    assert "Hoàn tất" in peer_reply
    assert "độ tin cậy trung bình" in peer_reply
    assert "VALID" not in peer_reply
    rank_reply = answer("Xep hang DOM cua ZURICH-20.022", SERVICE)
    assert "phân vị" in rank_reply
    assert "65,9%" in rank_reply
