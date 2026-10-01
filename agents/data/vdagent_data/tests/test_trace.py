"""The working trace of a Data step: what the agent really did, as structured events (no prose).

`run_step(step, tools, observer)` reports every real action to an optional observer. The events carry facts read from
the run itself (table, rows, hash, ids, codes) and never row values, so a narrator can turn them into natural language
without any hardcoded result. The tests hold the trace to the truth: it must equal the lineage stored in the artifacts.
"""

from __future__ import annotations

from typing import Any

import pytest

from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import McpPort
from vdagent_data.tests.test_steps import artifacts_of, step
from vdagent_data.trace import TraceEvent

SUBJECT_ONLY = {"subject_unit_code": "A12-08"}


class Recorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


class Exploding:
    async def emit(self, event: TraceEvent) -> None:
        raise RuntimeError("the observer is broken")


async def traced(port: McpPort, **kwargs: Any):  # noqa: ANN201
    rec = Recorder()
    report = await run_step(step(**kwargs), port, observer=rec)
    return report, rec.events


def stages(events: list[TraceEvent]) -> list[str]:
    return [e.stage for e in events]


# ---- the trace follows the real order of work ------------------------------------------------------------------------


async def test_the_trace_follows_the_real_order_of_work(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY)
    assert report.state == "completed"
    seq = stages(events)
    assert seq[0] == "intake" and seq[-1] == "done"
    first = lambda s: seq.index(s)  # noqa: E731
    last = lambda s: len(seq) - 1 - seq[::-1].index(s)  # noqa: E731
    assert first("intake") < first("scope") < first("read") < first("snapshot") < first("config")
    assert last("read") < first("check") < first("write") < last("write") < seq.index("done")


async def test_the_trace_needs_no_observer_and_the_result_is_the_same(alice: McpPort) -> None:
    plain = await run_step(step(spec=SUBJECT_ONLY), alice)
    report, _ = await traced(alice, spec=SUBJECT_ONLY)
    assert (plain.state, sorted(r.artifact_type.value for r in plain.artifact_refs), plain.warnings) == (
        report.state, sorted(r.artifact_type.value for r in report.artifact_refs), report.warnings)


async def test_a_broken_observer_never_changes_the_result(alice: McpPort) -> None:
    report = await run_step(step(spec=SUBJECT_ONLY), alice, observer=Exploding())
    assert report.state == "completed" and len(report.artifact_refs) == 3


# ---- the trace is true: it equals the lineage stored in the artifacts -------------------------------------------------


async def test_every_read_in_the_trace_is_a_query_recorded_in_the_dataset(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY)
    arts = await artifacts_of(alice, report)
    reads = [e for e in events if e.stage == "read" and e.state == "end"]
    assert [{"table": e.facts["table"], "sql_sha256": e.facts["sql_sha256"], "row_count": e.facts["rows"]} for e in reads] == (
        arts["dataset"]["payload"]["queries"])


async def test_every_write_in_the_trace_is_a_stored_artifact(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY)
    writes = [e for e in events if e.stage == "write" and e.state == "end"]
    assert [(e.facts["artifact_type"], e.facts["artifact_id"], e.facts["version"]) for e in writes] == [
        (r.artifact_type.value, r.artifact_id, r.version) for r in report.artifact_refs]
    assert all(e.facts["status"] in ("VALID", "PARTIAL") and e.facts["size_bytes"] > 0 for e in writes)


async def test_the_scope_in_the_trace_is_the_backends_not_the_steps(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY,
                             user_context={"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-Z"], "zone_ids": []}})
    [scope] = [e for e in events if e.stage == "scope"]
    assert scope.facts["project_ids"] == ["PRJ-X"]


async def test_the_snapshot_and_the_config_come_from_the_warehouse(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    [snapshot] = [e for e in events if e.stage == "snapshot"]
    assert snapshot.facts["snapshot_id"] == "SNAP-2026-09-28" and snapshot.facts["snapshot_date"] == "2026-09-28"
    assert snapshot.facts["semantic_config_version"] == "sc-1"
    [config] = [e for e in events if e.stage == "config"]
    assert "peer_area_tolerance_pct" in config.facts["approved"] and "min_group_size" in config.facts["pending"]


async def test_the_check_reports_what_the_quality_check_found(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY)
    arts = await artifacts_of(alice, report)
    [check] = [e for e in events if e.stage == "check"]
    assert check.facts["overall_status"] == arts["dq"]["payload"]["overall_status"]
    assert check.facts["limitations"] == arts["dq"]["limitations"]


async def test_the_done_event_matches_the_report(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY)
    done = events[-1]
    assert done.facts == {"state": "completed", "artifacts": 3, "warnings": len(report.warnings), "partial": report.partial}


# ---- the trace is honest about failure -------------------------------------------------------------------------------


async def test_a_refused_snapshot_ends_in_a_fail_event_and_writes_nothing(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY, snapshot_id="SNAP-NOPE")
    assert report.state == "rejected"
    assert events[-1].stage == "fail" and events[-1].facts["code"] == "SNAPSHOT_UNKNOWN" and events[-1].facts["state"] == "rejected"
    assert "write" not in stages(events) and "done" not in stages(events)


async def test_a_missing_snapshot_fails_before_any_read(alice: McpPort) -> None:
    report, events = await traced(alice, spec=SUBJECT_ONLY, snapshot_id=None)
    assert report.state == "rejected" and stages(events) == ["intake", "fail"]


async def test_an_unknown_unit_fails_after_the_reads_that_showed_it(alice: McpPort) -> None:
    report, events = await traced(alice, spec={"subject_unit_code": "ZZ9-99"})
    assert report.state == "failed" and events[-1].facts["code"] == "UNIT_NOT_FOUND"
    reads = [e for e in events if e.stage == "read" and e.state == "end" and e.facts["table"] == "dim_unit_master"]
    assert reads and reads[-1].facts["rows"] == 0


async def test_aggregate_metrics_is_traced_too(alice: McpPort) -> None:
    report, events = await traced(alice, operation="aggregate_metrics", spec={"metrics": ["dom_days"], "group_by": ["zone_key"]})
    assert report.state == "completed" and stages(events)[0] == "intake" and stages(events)[-1] == "done"
    assert stages(events).count("write") == 6  # start + end for dataset, metric and dq


# ---- shape of the events ---------------------------------------------------------------------------------------------


async def test_every_call_is_a_start_and_an_end_that_never_interleave(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    open_id: str | None = None
    seen: set[str] = set()
    for e in events:
        if e.state == "start":
            assert open_id is None and e.call_id and e.call_id not in seen
            open_id = e.call_id
            seen.add(e.call_id)
        elif e.state == "end":
            assert e.call_id == open_id
            open_id = None
        else:
            assert e.state == "note" and e.call_id is None
    assert open_id is None
    assert {e.stage for e in events if e.state in ("start", "end")} == {"read", "write"}


async def test_every_action_says_why_it_is_done(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    starts = [e for e in events if e.state == "start"]
    assert starts and all(e.purpose.strip() for e in starts)
    assert len({e.purpose for e in starts if e.stage == "read"}) > 1  # each read has its own reason, not one shared line


async def test_events_carry_metadata_never_row_values(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    scalars = (str, int, float, bool, type(None))
    for e in events:
        for key, value in e.facts.items():
            assert isinstance(value, scalars) or (isinstance(value, list) and all(isinstance(v, scalars) for v in value)), (e.stage, key)
    blob = repr([e.facts for e in events])
    assert "63.02" not in blob and "72500000" not in blob  # the subject's area and price are row values


@pytest.mark.parametrize("state", ["note", "start", "end"])
def test_a_trace_event_is_frozen_and_named(state: str) -> None:
    event = TraceEvent(stage="read", state=state, call_id=None if state == "note" else "c1", purpose="p", facts={"table": "t"})  # type: ignore[arg-type]
    with pytest.raises(Exception):  # noqa: B017
        event.stage = "write"  # type: ignore[misc]


# ---- phases: the trace says which stage of the pipeline each event belongs to -----------------------------------------


async def test_every_event_belongs_to_a_phase_and_phases_never_reappear(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    phases = [e.phase for e in events]
    assert all(phases)
    compact = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
    assert compact == ["intake", "snapshot", "resolve", "fetch", "funnel", "check", "write", "done"]


async def test_the_aggregate_phases_skip_what_it_does_not_do(alice: McpPort) -> None:
    _, events = await traced(alice, operation="aggregate_metrics", spec={"metrics": ["dom_days"]})
    phases = [e.phase for e in events]
    compact = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
    assert compact == ["intake", "snapshot", "resolve", "check", "write", "done"]


async def test_a_failure_keeps_the_phase_it_happened_in(alice: McpPort) -> None:
    _, events = await traced(alice, spec={"subject_unit_code": "ZZ9-99"})
    assert [e.phase for e in events][-2:] == ["resolve", "fail"] and events[-1].facts["code"] == "UNIT_NOT_FOUND"


async def test_a_tool_call_names_the_real_tool_it_made(alice: McpPort) -> None:
    _, events = await traced(alice, spec=SUBJECT_ONLY)
    tools = {(e.stage, e.facts["tool"]) for e in events if e.state == "start"}
    assert tools == {("read", "re_run_query"), ("write", "artifact_put")}
