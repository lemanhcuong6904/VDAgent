"""Wave dispatcher (D3; build spec 01 §8–9 RCV-5 as far as it applies, §6.3 snapshot pin; source §13 V3, V9, V13)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any

from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, render_agent_report
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.dispatcher import TIMEOUT_REPLY, Outbound, drive
from vdagent_orchestrator.intent import IntentDraft, decide
from vdagent_orchestrator.planning import DraftStep, PlanDraft, build_plan
from vdagent_orchestrator.records import RunRecord, new_run

REGISTRY = CatalogRegistry.load()
USER = UserContext.model_validate({"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X"]}})
SCOPE = {"mentions": [{"text": "Landmark", "kind_hint": "ZONE"}], "scope_all": False}
KIND = {"fetch_units": ArtifactType.DATA_PACKAGE, "aggregate_metrics": ArtifactType.DATA_PACKAGE,
        "explain_slow_moving": ArtifactType.INSIGHT}

Handler = Callable[[StepSpec], AgentReport | str]


def frame(task_kinds: list[str], outputs: list[str]) -> Any:
    draft = IntentDraft.model_validate({"scope_check": "ANALYSIS", "task_kinds": task_kinds, "phenomena": ["bán chậm"],
                                        "metrics": ["avg_dom_unsold"], "requested_outputs": outputs,
                                        "mentions": [{"text": "Landmark", "kind_hint": "ZONE"}]})
    result = decide(draft, question="Tại sao phân khu Landmark bán chậm?", served=REGISTRY.served_kinds())
    assert result.frame is not None
    return result.frame


def step(step_id: str, agent: str, operation: str, inputs: Sequence[str] = (), **spec: Any) -> DraftStep:
    return DraftStep(step_id=step_id, agent=agent, operation=operation, spec=spec, inputs=list(inputs), objective=operation)


def run_of(steps: list[DraftStep], *, pinned: bool = False, kinds: tuple[list[str], list[str]] = (["LOOKUP"], ["CHAT_ANSWER"])) -> RunRecord:
    plan = build_plan(PlanDraft(steps=steps), run_id="run-1", plan_id="plan-1", registry=REGISTRY, next_step_no=1,
                      snapshot_pinned=pinned)
    return new_run(plan, frame(*kinds), user_context=USER, snapshot_id="snap-0" if pinned else None)


def done(spec: StepSpec, *, snapshot: str = "snap-1", **fields: Any) -> AgentReport:
    ref = ArtifactRef(artifact_id=f"art-{spec.step_id}", version=1, artifact_type=KIND.get(spec.operation, ArtifactType.DATA_PACKAGE))
    return AgentReport(run_id=spec.run_id, step_id=spec.step_id, idempotency_key=spec.idempotency_key, state="completed",
                       artifact_refs=[ref], snapshot_id=snapshot, semantic_config_version="sc-1",
                       summary=f"{spec.step_id} xong", **fields)


def fail(spec: StepSpec, code: str) -> AgentReport:
    return AgentReport(run_id=spec.run_id, step_id=spec.step_id, idempotency_key=spec.idempotency_key, state="failed",
                       error={"code": code, "message": "lỗi"})  # type: ignore[arg-type]


class FakeSender:
    def __init__(self, handlers: dict[str, Handler]) -> None:
        self.handlers = handlers
        self.waves: list[list[Outbound]] = []
        self.specs: dict[str, StepSpec] = {}

    async def send(self, wave: Sequence[Outbound]) -> list[str]:
        self.waves.append(list(wave))
        replies = []
        for item in wave:
            spec = StepSpec.model_validate_json(item.message)
            self.specs[spec.step_id] = spec
            reply = self.handlers[spec.step_id](spec)
            replies.append(reply if isinstance(reply, str) else render_agent_report("Xong.", reply))
        return replies


def go(run: RunRecord, sender: FakeSender, *, tier2: bool = False) -> RunRecord:
    return asyncio.run(drive(run, sender=sender, registry=REGISTRY, tier2_available=tier2))


def test_wave_sends_parallel_send_to_agent_in_one_emit() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                  step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"])],
                 pinned=True, kinds=(["EXPLAIN"], ["CHAT_ANSWER"]))
    sender = FakeSender({"B1": done, "B2": done, "B3": done})
    run = go(run, sender)
    assert [[o.step_id for o in wave] for wave in sender.waves] == [["B1", "B2"], ["B3"]]
    assert [o.agent for o in sender.waves[0]] == ["data", "data"]
    b3 = sender.specs["B3"]
    assert [r.artifact_id for r in b3.input_refs] == ["art-B1", "art-B2"] and b3.snapshot_id == "snap-0"
    assert json.loads(sender.waves[1][0].message)["contract"] == "StepSpec@1"
    assert run.finished and run.status == "completed"


def test_unparseable_report_fatal() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                  step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"])],
                 pinned=True, kinds=(["EXPLAIN"], ["CHAT_ANSWER"]))
    run = go(run, FakeSender({"B1": done, "B2": done, "B3": lambda spec: "Tôi xong rồi nhé (không có JSON)"}))
    b3 = run.steps["B3"]
    assert b3.status == "failed" and b3.error_code == "REPORT_UNPARSEABLE" and b3.error_class is ErrorClass.FATAL
    assert any(a["kind"] == "FATAL" for a in run.ops_alerts)
    assert run.finished and run.status == "partial"  # the analytical step is missing, data is complete


def test_v3_two_data_steps_one_snapshot() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])])
    sender = FakeSender({"B1": lambda s: done(s, snapshot="snap-A"), "B2": lambda s: done(s, snapshot="snap-A")})
    run = go(run, sender)
    assert [[o.step_id for o in w] for w in sender.waves] == [["B1"], ["B2"]]
    assert sender.specs["B1"].snapshot_id is None and sender.specs["B2"].snapshot_id == "snap-A"
    assert run.snapshot_id == "snap-A" and run.semantic_config_version == "sc-1"
    assert sender.specs["B2"].input_refs == []  # snapshot-only wait carries no package


def test_v3_first_data_fails_second_locks_snapshot() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                  step("B3", "data", "aggregate_metrics", scope=SCOPE, metrics=["unit_count"])])
    sender = FakeSender({"B1": lambda s: fail(s, "DATA_UNAVAILABLE"), "B2": lambda s: done(s, snapshot="snap-B"),
                         "B3": lambda s: done(s, snapshot="snap-B")})
    run = go(run, sender)
    assert [[o.step_id for o in w] for w in sender.waves] == [["B1"], ["B2"], ["B3"]]
    assert sender.specs["B3"].snapshot_id == "snap-B" and run.snapshot_id == "snap-B"
    assert run.steps["B1"].status == "failed" and run.status == "failed"  # a Data step never completed (FIN-3)


def test_v9_partial_small_sample_warning() -> None:
    run = run_of([step("B1", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])], pinned=True)
    run = go(run, FakeSender({"B1": lambda s: done(s, partial=True, warnings=["SMALL_SAMPLE"], data_confidence="LOW")}))
    b1 = run.steps["B1"]
    assert b1.status == "completed" and b1.partial and b1.warnings == ["SMALL_SAMPLE"] and b1.data_confidence == "LOW"
    assert run.status == "completed" and run.warnings == [{"step_id": "B1", "code": "SMALL_SAMPLE"}]


def test_v13_two_last_steps_close_once() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])], pinned=True)
    sender = FakeSender({"B1": done, "B2": done})
    run = go(run, sender)
    run = go(run, sender)  # driving a finished run changes nothing
    assert [e["event"] for e in run.events].count("RUN_FINISHED") == 1 and len(sender.waves) == 1


def test_deadline_from_catalog_seconds() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE)], pinned=True)
    sender = FakeSender({"B1": lambda s: TIMEOUT_REPLY})
    run = go(run, sender)
    assert sender.specs["B1"].deadline_s == 90 and sender.waves[0][0].timeout_s == 105  # catalog + 15 s grace
    assert run.steps["B1"].error_code == "TIMEOUT" and any(a["kind"] == "TIMEOUT" for a in run.ops_alerts)
