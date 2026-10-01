"""The dataset says why it was fetched: the question, the operation and how every named entity was resolved.

The explanation chat (answers about what Data fetched) reads this record from the stored `re_dataset@1`; it cannot be
rebuilt later from the live trace. Every path that writes a dataset records it, and the record holds no row values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vdagent_contracts.messages import StepSpec

from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import ALICE, McpPort
from vdagent_data.tests.test_v1_peers_context import (  # noqa: F401  (`edited` is a fixture)
    edited,
    min_peers,
)
from vdagent_data.tests.test_v1_steps import artifacts_of, ent, v1
from vdagent_data.v1 import V1Result, run_step_v1


async def request_of(port: McpPort, result: V1Result) -> dict[str, Any]:
    return (await artifacts_of(port, result))["dataset"]["payload"]["request"]


async def test_one_unit_records_the_question_and_how_the_code_was_matched(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("a12 08")]}, question="Vì sao căn a12 08 bán chậm?"), alice)
    assert r.report.state == "completed", r.report.error
    request = await request_of(alice, r)
    assert request["operation"] == "fetch_units"
    assert request["original_question"] == "Vì sao căn a12 08 bán chậm?"
    [entity] = request["resolved_entities"]
    assert entity["mention"] == "a12 08" and entity["kind"] == "UNIT" and entity["name"] == "A12-08"
    assert entity["method"] == "normalized"  # the typed form differs from the stored code


async def test_a_zone_records_its_level_and_method(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]}, question="Tình hình phân khu Tòa Aqua 1?"), alice)
    [entity] = (await request_of(alice, r))["resolved_entities"]
    assert (entity["mention"], entity["kind"], entity["name"]) == ("Tòa Aqua 1", "ZONE", "Tòa Aqua 1")
    assert entity["method"] == "exact"


async def test_a_whole_scope_step_records_no_entity(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"scope_all": True, "filters": ["slow_moving"]}, question="căn nào bán chậm?"), alice)
    request = await request_of(alice, r)
    assert request["resolved_entities"] == [] and request["original_question"] == "căn nào bán chậm?"


async def test_peers_record_the_target_unit(edited: Callable[..., McpPort]) -> None:  # noqa: F811
    port = edited(min_peers(5))
    r = await run_step_v1(v1("fetch_peer_candidates", {"entities": [ent("A12-08", "UNIT")]}, question="So sánh căn A12-08"), port)
    assert r.report.state == "completed", r.report.error
    request = await request_of(port, r)
    assert request["operation"] == "fetch_peer_candidates"
    assert [e["name"] for e in request["resolved_entities"]] == ["A12-08"]


async def test_the_older_subject_step_records_its_unit_and_question(alice: McpPort) -> None:
    step = StepSpec.model_validate({
        "run_id": f"t_{ALICE}", "plan_id": "pl_old", "step_id": "B1", "idempotency_key": "pl_old:B1", "operation": "fetch_units",
        "spec": {"subject_unit_code": "A12-08", "population": "subject"},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": [], "zone_ids": []}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1", "original_question": "Vì sao căn A12-08 bán chậm?",
    })
    report = await run_step(step, alice)
    assert report.state == "completed", report.error
    refs = {r.artifact_type.value: r for r in report.artifact_refs}
    got = await alice.call("artifact_get", {"artifact_id": refs["dataset"].artifact_id, "version": refs["dataset"].version})
    request = got["payload"]["request"]
    assert request["original_question"] == "Vì sao căn A12-08 bán chậm?"
    [entity] = request["resolved_entities"]
    assert (entity["kind"], entity["name"], entity["method"]) == ("UNIT", "A12-08", "subject_unit_code")


async def test_the_record_holds_no_row_values(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")]}), alice)
    request = await request_of(alice, r)
    assert set(request) == {"operation", "original_question", "resolved_entities"}
    assert all(set(e) == {"mention", "kind", "id", "name", "method"} for e in request["resolved_entities"])
