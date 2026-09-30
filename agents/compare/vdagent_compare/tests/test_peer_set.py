"""Spec v5.3 §1.5: Data owns the peer rule. Compare reads `peer_set` as given, never re-filters it."""
from __future__ import annotations

import logging

from vdagent_compare.vh_service import CompareService

HERO = {"entityType": "unit", "entityCode": "A12-08"}
# What Data's rule returns for A12-08: the 5 v5.2 peers plus A13-06, sold (Data does not filter status).
STRICT = ["U815", "U801", "U820", "U833", "U841", "U904"]


def peer_set(rows, constrained=False):
    return {"packageId": "pkg_peer_hero", "isPeerSampleConstrained": constrained, "rows": rows}


def strict(*keys):
    return [{"unit_key": key, "match_tier": "strict"} for key in keys]


def test_uses_every_row_of_the_peer_set_and_keeps_the_numbers():
    result = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT))})
    pd, cmp = result["peer_definition"], result["comparison"]
    assert pd["peerCount"] == 6
    assert pd["relaxation"]["source"] == "data"
    assert "A13-06" in [p["entityCode"] for p in pd["peers"]]
    metrics = {row["metric"]: row for row in cmp["metrics"]}
    assert (metrics["net_asking_price_per_m2"]["benchmark"]["value"], metrics["dom"]["benchmark"]["value"]) == (
        62_500_000, 48)
    assert cmp["dataSufficiency"]["level"] == "LIMITED"
    assert cmp["input_artifact_refs"][-2:] == ["pkg_peer_hero", pd["artifact_id"]]


def test_expanded_rows_mark_the_sample_constrained():
    rows = strict("U815", "U801", "U820") + [
        {"unit_key": "U805", "match_tier": "expanded"}, {"unit_key": "U857", "match_tier": "expanded"}]
    result = CompareService().run({"subject": HERO, "peerSet": peer_set(rows)})
    assert result["peer_definition"]["relaxation"]["isPeerSampleConstrained"] is True
    assert result["comparison"]["confidence"] in {"low", "medium"}
    assert "PEER_SAMPLE_CONSTRAINED" in result["comparison"]["dataSufficiency"]["reasons"]


def test_excluded_rows_become_the_exclusion_list_and_are_never_peers():
    rows = strict(*STRICT) + [{"unit_key": "U805", "match_tier": "excluded", "exclusion_reason": "different_floor_band"}]
    pd = CompareService().run({"subject": HERO, "peerSet": peer_set(rows)})["peer_definition"]
    assert pd["peerCount"] == 6
    assert pd["excludedPeers"] == [{"entityId": "U805", "entityCode": "A06-01", "reason": "different_floor_band"}]
    assert pd["excludedSummary"] == {"different_floor_band": 1}


def test_without_excluded_rows_the_exclusion_list_is_empty():
    pd = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT))})["peer_definition"]
    assert (pd["excludedPeers"], pd["excludedSummary"]) == ([], {})


def test_fewer_than_five_rows_is_insufficient_and_compare_does_not_widen():
    result = CompareService().run({"subject": HERO, "peerSet": peer_set(strict("U815", "U801", "U820"))})
    cmp = result["comparison"]
    assert (cmp["status"], cmp["reason_code"]) == ("PARTIAL", "INSUFFICIENT_EVIDENCE")
    assert cmp["dataSufficiency"]["level"] == "INSUFFICIENT"
    assert [a["peerCount"] for a in result["peer_definition"]["attemptedCriteria"]] == [3]


def test_user_narrowing_happens_inside_the_peer_set_without_widening():
    result = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT)),
                                   "criteriaOverride": {"mustMatch": ["zone_id"]}})
    pd = result["peer_definition"]
    assert pd["peerCount"] == 4  # ZN-B units B09-05 and B11-07 leave; nothing is added back
    assert result["comparison"]["dataSufficiency"]["level"] == "INSUFFICIENT"
    assert any("không mở thêm nhóm tầng" in line for line in result["comparison"]["limitations"])


def test_peer_set_containing_the_subject_is_rejected_whole():
    cmp = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT, "U812"))})["comparison"]
    assert (cmp["status"], cmp["reason_code"]) == ("INVALID", "UPSTREAM_NOT_VALID")


def test_peer_of_another_unit_type_is_rejected_not_silently_dropped():
    cmp = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT, "U903"))})["comparison"]
    assert (cmp["status"], cmp["reason_code"]) == ("INVALID", "UPSTREAM_NOT_VALID")
    assert "A11-04" in cmp["reason"]


def test_unknown_unit_key_is_rejected():
    cmp = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT, "U999"))})["comparison"]
    assert (cmp["status"], cmp["reason_code"]) == ("INVALID", "UPSTREAM_NOT_VALID")


def test_disagreement_with_compares_own_rule_is_logged_not_applied(caplog):
    caplog.set_level(logging.WARNING, logger="vdagent_compare")
    result = CompareService().run({"subject": HERO, "peerSet": peer_set(strict(*STRICT))})
    assert result["peer_definition"]["peerCount"] == 6  # Data's answer stands
    assert any("PEER_RULE_DRIFT" in record.getMessage() and "U904" in record.getMessage()
               for record in caplog.records)
