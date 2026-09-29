"""Spec v5.3 §2.4: how far a comparison may go with the data at hand (FULL / LIMITED / INSUFFICIENT)."""
from __future__ import annotations

from decimal import Decimal

from vdagent_compare.vh_data import Unit
from vdagent_compare.vh_service import CompareService
from vdagent_compare.vh_sufficiency import assess

PRICE, DOM = "net_asking_price_per_m2", "dom"


def unit(i: int, *, price=60_000_000, dom=50, status="available") -> Unit:
    return Unit(
        unit_id=f"U{i}", unit_code=f"C{i}", project_id="P", zone_id="Z", unit_type="2PN",
        area_m2=Decimal("68"), floor_band="MID", balcony_orientation="SE", view_type="CITY",
        status=status, launch_batch_id="B",
        metrics={PRICE: None if price is None else Decimal(price), DOM: None if dom is None else Decimal(dom)},
    )


SUBJECT = unit(0, price=72_000_000, dom=138)


def peers(n: int, **overrides) -> list[Unit]:
    return [unit(i + 1, **overrides) for i in range(n)]


def per(result: dict, metric: str) -> dict:
    return next(row for row in result["perMetric"] if row["metric"] == metric)


def test_ten_strict_peers_with_full_data_is_full():
    result = assess(SUBJECT, peers(12), [PRICE, DOM], constrained=False)
    assert result["level"] == "FULL"
    assert result["reasons"] == []
    assert per(result, PRICE) == {"metric": PRICE, "n": 12, "applicable": 12, "coveragePct": 100.0, "use": "full"}


def test_five_to_nine_peers_is_limited_small_sample():
    result = assess(SUBJECT, peers(6), [PRICE, DOM], constrained=False)
    assert result["level"] == "LIMITED"
    assert result["reasons"] == ["SMALL_SAMPLE"]
    assert per(result, DOM)["use"] == "limited"


def test_expanded_floor_band_caps_at_limited():
    result = assess(SUBJECT, peers(12), [PRICE, DOM], constrained=True)
    assert result["level"] == "LIMITED"
    assert result["reasons"] == ["PEER_SAMPLE_CONSTRAINED"]


def test_coverage_between_50_and_79_percent_is_limited():
    group = peers(4, price=None) + peers(8)  # price on 8 of 12 = 66.67 %
    result = assess(SUBJECT, group, [PRICE, DOM], constrained=False)
    assert per(result, PRICE) == {"metric": PRICE, "n": 8, "applicable": 12, "coveragePct": 66.67, "use": "limited"}
    assert result["level"] == "LIMITED"
    assert result["reasons"] == ["LOW_COVERAGE"]


def test_coverage_below_half_drops_the_metric_even_with_five_values():
    group = peers(7, price=None) + peers(5)  # price on 5 of 12 = 41.67 %
    result = assess(SUBJECT, group, [PRICE, DOM], constrained=False)
    assert per(result, PRICE)["use"] == "dropped"
    assert per(result, DOM)["use"] == "full"
    assert (result["level"], result["reasons"]) == ("LIMITED", ["METRIC_DROPPED"])


def test_dom_only_counts_peers_still_for_sale():
    group = peers(4, dom=None, status="sold") + peers(8)
    result = assess(SUBJECT, group, [PRICE, DOM], constrained=False)
    assert per(result, DOM) == {"metric": DOM, "n": 8, "applicable": 8, "coveragePct": 100.0, "use": "limited"}
    assert per(result, PRICE)["applicable"] == 12


def test_subject_without_a_value_drops_that_metric():
    result = assess(unit(0, price=None), peers(12), [PRICE, DOM], constrained=False)
    assert per(result, PRICE)["use"] == "dropped"
    assert result["level"] == "LIMITED"


def test_fewer_than_five_peers_is_insufficient():
    result = assess(SUBJECT, peers(4), [PRICE, DOM], constrained=True)
    assert result["level"] == "INSUFFICIENT"
    assert "SMALL_SAMPLE" in result["reasons"]


def test_no_usable_metric_is_insufficient():
    result = assess(SUBJECT, peers(6, price=None, dom=None), [PRICE, DOM], constrained=False)
    assert result["level"] == "INSUFFICIENT"
    assert result["reasons"] == ["SMALL_SAMPLE", "METRIC_DROPPED"]


def test_hero_is_limited_and_says_so_first():
    cmp = CompareService().run({"subject": {"entityType": "unit", "entityCode": "A12-08"}})["comparison"]
    assert cmp["dataSufficiency"]["level"] == "LIMITED"
    assert cmp["dataSufficiency"]["reasons"] == ["SMALL_SAMPLE"]
    assert cmp["dataSufficiency"]["summary"].startswith("So sánh có giới hạn")


def test_insufficient_group_suggests_other_steps_without_numbers():
    cmp = CompareService().run({
        "subject": {"entityType": "unit", "entityCode": "A12-08"},
        "criteriaOverride": {"mustMatch": ["zone_id"]},
    })["comparison"]
    assert (cmp["status"], cmp["reason_code"]) == ("PARTIAL", "INSUFFICIENT_EVIDENCE")
    assert cmp["dataSufficiency"]["level"] == "INSUFFICIENT"
    assert cmp["metrics"] == []
    steps = cmp["suggestedNextSteps"]
    assert [s["operation"] for s in steps] == ["compare_head_to_head", "compare_ranking", "compare_cohort"]
    assert steps[0]["target"]["entityCode"]  # the closest near-miss unit
    assert steps[2]["cohortDimension"] == "floor_band"


def test_rendered_answer_leads_with_the_level():
    from vdagent_compare.vh_chat import render

    text = render(CompareService().run({"subject": {"entityType": "unit", "entityCode": "A12-08"}}))
    assert "Mức dữ liệu: **Hạn chế**" in text
    assert text.index("So sánh có giới hạn") < text.index("Trung vị nhóm")


def test_rendered_insufficient_answer_lists_next_steps():
    from vdagent_compare.vh_chat import render

    text = render(CompareService().run({
        "subject": {"entityType": "unit", "entityCode": "A12-08"},
        "criteriaOverride": {"mustMatch": ["zone_id"]},
    }))
    assert "Mức dữ liệu: **Không đủ**" in text
    assert "Có thể hỏi cách khác:" in text
    assert "So trực diện A12-08" in text


def test_insufficient_summary_counts_the_real_group_and_suggests_a_unit_for_sale():
    service = CompareService()
    cmp = service.run({
        "subject": {"entityType": "unit", "entityCode": "A12-08"},
        "criteriaOverride": {"mustMatch": ["zone_id"]},
    })["comparison"]
    assert "nhóm 4 căn" in cmp["dataSufficiency"]["summary"]
    assert cmp["dataSufficiency"]["reasons"] == ["SMALL_SAMPLE", "PEER_SAMPLE_CONSTRAINED"]
    target = cmp["suggestedNextSteps"][0]["target"]["entityCode"]
    assert target in {"A12-11", "A10-02", "A14-03"}  # same zone, met the rule, still for sale


def test_ranking_order_uses_contract_names_and_accepts_the_old_one():
    service = CompareService()
    base = {"subject": {"entityType": "zone", "entityCode": "ZN-A"}, "comparisonMode": "ranking",
            "metricsRequested": ["dom"]}
    default = service.run(base)["comparison"]["rankingList"]["order"]
    legacy = service.run({**base, "rankingOptions": {"order": "attention"}})["comparison"]["rankingList"]["order"]
    best = service.run({**base, "rankingOptions": {"order": "best_first"}})["comparison"]["rankingList"]["order"]
    assert (default, legacy, best) == ("attention_first", "attention_first", "best_first")
