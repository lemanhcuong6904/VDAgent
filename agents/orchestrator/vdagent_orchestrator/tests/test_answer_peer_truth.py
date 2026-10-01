"""The chat answer states one peer truth — Compare's — next to the Insight finding that needs it."""

from __future__ import annotations

import copy
from typing import Any

from vdagent_contracts.tests.test_insight_evidence import COMPARISON, evidence
from vdagent_orchestrator.answer import insight_lines


def insight(**claim: Any) -> dict[str, Any]:
    return {"artifact_id": "art_ins", "version": 1, "payload": {
        "evidence": evidence(),
        "insight": {"insights": [{"insight_id": "INS-001", "cause_code": "SEVERE_PHYSICAL_DEFECT", "claim": {
            "rendered_text": "Căn OCP-U00005 tồn 364 ngày; yếu tố có khả năng liên quan: khuyết điểm vật lý.",
            "numeric_bindings": [{"slot": "dom", "value": "364",
                                  "metric_ref": "x~insight#/fact_unit_inventory_snapshot/0/unsold_days_dom"}], **claim}}]}}}


def test_a_peer_based_finding_carries_compares_value_count_and_artifact() -> None:
    lines, codes = insight_lines(insight(), COMPARISON)
    assert codes == [] and len(lines) == 1
    assert "9,59%" in lines[0] and "5 căn" in lines[0] and "[art_cmp]" in lines[0] and "[art_ins]" in lines[0]


def test_without_a_comparison_the_need_is_stated_and_no_number_invented() -> None:
    [line], _ = insight_lines(insight(), None)
    assert "cần bước so sánh" in line and "%" not in line


def test_a_narrated_peer_number_is_withheld_and_reported() -> None:
    stale = insight()
    claim = stale["payload"]["insight"]["insights"][0]["claim"]
    claim["rendered_text"] += " Cao hơn peer +12,38%."
    claim["numeric_bindings"].append({"slot": "spread", "value": "12.38",
                                      "metric_ref": "x~insight#/dm_unit_friction_diagnostics/0/price_spread_vs_peer_pct"})
    [line], codes = insight_lines(copy.deepcopy(stale), COMPARISON)
    assert "12,38" not in line and codes == ["PEER_BASIS_DIFFERS:INS-001:spread=12.38"]
