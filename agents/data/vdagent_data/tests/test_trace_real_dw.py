"""The trace of a Data step over the real warehouse in Postgres (skips without VDAGENT_TEST_PG_DSN)."""

from __future__ import annotations

from vdagent_data.steps import run_step
from vdagent_data.tests.test_real_dw import ALICE, SUBJECT, RealTools, artifacts_of, pytestmark, step, port, tools  # noqa: F401
from vdagent_data.trace import TraceEvent


class Recorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


async def test_the_real_trace_equals_the_real_lineage(tools: RealTools) -> None:  # noqa: F811
    p, rec = port(tools), Recorder()
    report = await run_step(step(ALICE, ["100"]), p, observer=rec)
    assert report.state == "completed"
    arts = await artifacts_of(p, report)
    reads = [e for e in rec.events if e.stage == "read" and e.state == "end"]
    assert [{"table": e.facts["table"], "sql_sha256": e.facts["sql_sha256"], "row_count": e.facts["rows"]} for e in reads] == (
        arts["dataset"]["payload"]["queries"])
    [snapshot] = [e for e in rec.events if e.stage == "snapshot"]
    assert snapshot.facts["snapshot_id"] == "SNAP-20260630-01" and snapshot.facts["snapshot_date"] == "2026-06-30"
    [scope] = [e for e in rec.events if e.stage == "scope"]
    assert scope.facts["project_ids"] == ["100", "400"]
    [config] = [e for e in rec.events if e.stage == "config"]
    assert {"overdue_threshold_days", "peer_area_tolerance_pct"} <= set(config.facts["approved"])
