"""Insight → Chart boundary, producer side: every `insight` artifact carries `insight_evidence@1` built from the
deterministic candidates (never from the narration), with each number pinned to the Data dataset it was read from."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vdagent_contracts.insight_evidence import METRICS, parse_evidence, peer_claims, resolve_pointer, same_value
from vdagent_data.tests.conftest import McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_insight.dw_reader import dw_field
from vdagent_insight.llm import FakeLlmClient, FakeReply
from vdagent_insight.llm.steps import LlmProviders
from vdagent_insight.settings import CONFIG_DIR, SemanticConfigRegistry, load_llm_config
from vdagent_insight.stepspec import StepEnv, run_step
from vdagent_insight.store import InsightStore
from vdagent_insight.tests.test_dw_integration import data_refs, insight_step
from vdagent_insight.tests.test_llm_fake import usage

DOM = "fact_unit_inventory_snapshot.unsold_days_dom"
SPREAD = "dm_unit_friction_diagnostics.price_spread_vs_peer_pct"
PEERS = "dm_unit_friction_diagnostics.peer_n"
PRICE = "fact_unit_inventory_snapshot.net_price_per_m2"


def env(tmp_path: Path, providers: LlmProviders | None = None) -> StepEnv:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return StepEnv(registry=SemanticConfigRegistry(CONFIG_DIR), llm=load_llm_config(CONFIG_DIR / "llm.yaml"),
                   store=InsightStore(tmp_path / "insight.db"), providers=providers)


async def insight_artifact(port: McpPort, refs: list[dict[str, Any]], step_env: StepEnv, **over: Any) -> dict[str, Any]:
    report = await run_step(insight_step(refs, **over), port.as_agent("insight"), step_env)
    assert report.state == "completed", report
    [ref] = report.artifact_refs
    return await port.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})


def scripted(*templates: tuple[str, tuple[str, ...]]) -> LlmProviders:
    """An LLM that narrates candidate c1 with the given template and slots, then (if asked) repeats itself."""
    item = [{"candidate_ids": ["c1"], "template": t, "slots": [{"slot": s, "ref": f"c1.{s}"} for s in slots]} for t, slots in templates]
    reply = FakeReply({"selected": item, "skipped": []}, usage("MAIN"))
    return LlmProviders(FakeLlmClient([reply, FakeReply({"selected": item, "skipped": []}, usage("REPAIR"))]))


async def test_the_insight_artifact_carries_a_valid_evidence_block_pinned_to_its_dataset(alice: McpPort, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    art = await insight_artifact(alice, refs, env(tmp_path))
    ev = parse_evidence(art["payload"])
    assert ev.dataset_ref.model_dump(mode="json") == refs[0]  # the very dataset Insight read, pinned by hash
    assert ev.dataset_ref.model_dump(mode="json") in art["input_artifact_refs"]
    assert (ev.snapshot_id, ev.semantic_config_version) == ("SNAP-2026-09-28", "sc-1")
    assert ev.findings and all(f.finding_id.startswith("C-") for f in ev.findings)


async def test_every_number_resolves_exactly_in_the_data_dataset(alice: McpPort, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    art = await insight_artifact(alice, refs, env(tmp_path))
    dataset = await alice.call("artifact_get", {"artifact_id": refs[0]["artifact_id"], "version": refs[0]["version"]})
    pointers = [m for f in parse_evidence(art["payload"]).findings for m in f.metrics if m.source_ref]
    assert pointers
    for m in pointers:
        value = resolve_pointer(dataset["payload"], m.source_ref.split("#", 1)[1])
        assert same_value(value, m.value_exact), (m.metric_id, value, m.value_exact)


async def test_peer_facts_are_left_to_compare_in_evidence_and_narration(alice: McpPort, tmp_path: Path) -> None:
    art = await insight_artifact(alice, await data_refs(alice), env(tmp_path))
    [overpriced] = [f for f in parse_evidence(art["payload"]).findings if f.cause_code == "OVERPRICED_VS_PEER"]
    by_id = {m.metric_id: m for m in overpriced.metrics}
    assert by_id[DOM].role == "context" and by_id[DOM].chartable and by_id[DOM].value_exact == "138"
    assert SPREAD not in by_id and PEERS not in by_id  # the mart's own peer set: not Insight's to publish
    intents = {(i.question, tuple(i.metric_ids), i.requires) for i in overpriced.visual_intents}
    assert intents == {("current_value", (DOM,), None), ("target_vs_peer", (PRICE,), "comparison")}
    assert peer_claims(art["payload"]) == []  # TEMPLATE narration states no peer number either
    texts = " ".join(i["claim"]["rendered_text"] for i in art["payload"]["insight"]["insights"])
    assert "12,4" not in texts and "nhóm tương đồng" in texts  # the peer factor is named, its number is Compare's


async def test_an_llm_draft_binding_a_peer_number_never_reaches_the_artifact(alice: McpPort, tmp_path: Path) -> None:
    sneaky = scripted(("Căn {{unit}} đã tồn {{dom}}; có khả năng liên quan tới {{cause_label}}, cao hơn peer {{spread}}.",
                       ("unit", "dom", "cause_label", "spread")))
    art = await insight_artifact(alice, await data_refs(alice), env(tmp_path, sneaky))
    assert peer_claims(art["payload"]) == []
    assert "12,4" not in " ".join(i["claim"]["rendered_text"] for i in art["payload"]["insight"]["insights"])


async def test_a_finding_without_a_number_has_no_visual_intent(alice: McpPort, tmp_path: Path) -> None:
    art = await insight_artifact(alice, await data_refs(alice), env(tmp_path))
    limitation = [f for f in parse_evidence(art["payload"]).findings if f.insight_type != "ROOT_CAUSE_SIGNAL"]
    assert limitation and all(f.visual_intents == [] for f in limitation)


async def test_the_evidence_does_not_depend_on_what_the_narration_mentions(alice: McpPort, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    short = scripted(("Căn {{unit}} đã tồn {{dom}}; có khả năng liên quan tới {{cause_label}}.", ("unit", "dom", "cause_label")))
    long = scripted(("Căn {{unit}} đã tồn {{dom}}; có khả năng liên quan tới {{cause_label}} (điểm phạt khuyết tật {{defect}}).",
                     ("unit", "dom", "cause_label", "defect")))
    a = await insight_artifact(alice, refs, env(tmp_path / "a", short))
    b = await insight_artifact(alice, refs, env(tmp_path / "b", long))
    claims = [[[x["slot"] for x in i["claim"]["numeric_bindings"]] for i in art["payload"]["insight"]["insights"]] for art in (a, b)]
    assert claims[0] != claims[1]  # the two narrations really bound different numbers

    def facts(art: dict[str, Any]) -> list[Any]:
        return [(f.finding_id, [m.model_dump() for m in f.metrics], [i.model_dump() for i in f.visual_intents])
                for f in parse_evidence(art["payload"]).findings]

    assert facts(a) == facts(b)


async def test_an_idempotent_replay_returns_the_same_evidence(alice: McpPort, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    step_env = env(tmp_path)
    first = await insight_artifact(alice, refs, step_env)
    again = await insight_artifact(alice, refs, step_env)  # same idempotency key: the stored envelope is reused
    assert again["payload"]["evidence"] == first["payload"]["evidence"]


@pytest.mark.parametrize("version", ["sc-1", "3.1.0"])
def test_every_numeric_evidence_field_of_the_semantic_config_is_a_catalog_metric_with_its_unit(version: str) -> None:
    cfg = SemanticConfigRegistry(CONFIG_DIR).get(version)
    specs = [s for c in cfg.causes for s in [*c.required_evidence, *c.supplementary_evidence] if s.unit]
    assert specs
    for spec in specs:
        table, field, _ = dw_field(spec.table, spec.field)
        assert f"{table}.{field}" in METRICS, (spec.table, spec.field)
        assert METRICS[f"{table}.{field}"].unit == spec.unit, (spec.table, spec.field)


def test_rows_are_matched_on_text_keys_even_when_the_local_view_made_them_numbers() -> None:
    """D2: DW keys are TEXT ('101325'); Insight's row models coerce numeric-looking keys to int. The real DW has such
    keys (the mock's 'U-PRJ-X-A12-08' do not), so a pointer must match on the text form of the key."""
    from vdagent_insight.dw_reader import dataset_pointer

    dataset = {"tables": {"fact_unit_inventory_snapshot": [{"unit_key": "101324", "unsold_days_dom": 10},
                                                           {"unit_key": "101325", "unsold_days_dom": 364}],
                          "dim_sales_channel": [{"channel_key": "1004", "base_commission_pct": "1.10"}]}}
    local = {"unit_key": 101325, "channel_key": 1004, "unsold_days_dom": 364}
    assert dataset_pointer(dataset, "fact_unit_inventory_snapshot", local, "unsold_days_dom") == \
        "/tables/fact_unit_inventory_snapshot/1/unsold_days_dom"
    assert dataset_pointer(dataset, "fact_unit_inventory_snapshot", local, "base_commission_pct") == \
        "/tables/dim_sales_channel/0/base_commission_pct"
    assert dataset_pointer(dataset, "fact_unit_inventory_snapshot", {"unit_key": 999}, "unsold_days_dom") is None
