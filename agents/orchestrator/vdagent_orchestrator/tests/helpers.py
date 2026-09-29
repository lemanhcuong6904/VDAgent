"""Fakes for Orchestrator turns: worker agents answering StepSpecs, a scripted LLM, the MCP `get_user_context`."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from vdagent_agentkit.testing import ContractContext, FakeMcp, InMemoryMemory
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, render_agent_report
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.planning import DraftStep, PlanDraft

USER = UserContext.model_validate({"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X"]}})
SCOPE = {"mentions": [{"text": "Landmark", "kind_hint": "ZONE"}], "scope_all": False}
KIND = {"data": ArtifactType.DATA_PACKAGE, "insight": ArtifactType.INSIGHT, "chart": ArtifactType.CHART_SPEC,
        "report": ArtifactType.REPORT}

Behaviour = Callable[[StepSpec], AgentReport | str]


def done(spec: StepSpec, agent: str = "data", **fields: Any) -> AgentReport:
    ref = ArtifactRef(artifact_id=f"art-{spec.step_id}", version=1, artifact_type=KIND.get(agent, ArtifactType.DATA_PACKAGE))
    fields.setdefault("snapshot_id", "snap-1")
    return AgentReport(run_id=spec.run_id, step_id=spec.step_id, idempotency_key=spec.idempotency_key, state="completed",
                       artifact_refs=[ref], semantic_config_version="sc-1", summary=f"{spec.step_id} xong", **fields)


def ask(spec: StepSpec) -> AgentReport:
    return AgentReport(run_id=spec.run_id, step_id=spec.step_id, idempotency_key=spec.idempotency_key,
                       state="input_required", summary="Có 2 phân khu tên gần giống.",
                       question={"text": "Bạn muốn xem phân khu nào?", "input_id": f"{spec.step_id}:0",  # type: ignore[arg-type]
                                 "options": [{"id": "ZN-A", "label": "Tòa Landmark 1"}, {"id": "ZN-B", "label": "Landmark Plaza"}]})


class Workers:
    """Worker agents for `ContractContext.agents`: a behaviour per operation (default: done); records every StepSpec."""

    def __init__(self, behaviours: dict[str, Behaviour] | None = None) -> None:
        self.behaviours = behaviours or {}
        self.specs: list[tuple[str, StepSpec]] = []

    def handler(self, agent: str) -> Callable[[str], Awaitable[str]]:
        async def answer(message: str) -> str:
            spec = StepSpec.model_validate_json(message)
            self.specs.append((agent, spec))
            behaviour = self.behaviours.get(spec.operation, lambda s: done(s, agent))
            report = behaviour(spec)
            return report if isinstance(report, str) else render_agent_report("Xong.", report)
        return answer

    def agents(self) -> dict[str, Callable[[str], Awaitable[str]]]:
        return {name: self.handler(name) for name in ("data", "compare", "insight", "chart", "report")}

    def order(self) -> list[str]:
        return [s.step_id for _, s in self.specs]


def mcp(puts: list[dict[str, Any]] | None = None) -> FakeMcp:
    """`get_user_context` and a recording `artifact_put` (the Orchestrator's run_state / run_summary)."""
    stored = puts if puts is not None else []

    def put(args: dict[str, Any]) -> dict[str, Any]:
        stored.append({**json.loads(args["draft_json"]), "run_id": args.get("run_id")})
        return {"artifact_id": f"orc-{len(stored)}", "version": 1}

    return FakeMcp(handlers={"get_user_context": lambda args: USER.model_dump(mode="json"), "artifact_put": put})


def ctx(inbound: str, workers: Workers, memory: InMemoryMemory, **kwargs: Any) -> ContractContext:
    return ContractContext(inbound=f"[from: user] {inbound}", agents=workers.agents(), memory_store=memory, **kwargs)


def intent(task_kinds: list[str], *, mentions: list[str] = ("Landmark",), **fields: Any) -> str:  # type: ignore[assignment]
    body = {"scope_check": "ANALYSIS", "task_kinds": task_kinds,
            "mentions": [{"text": m, "kind_hint": "ZONE"} for m in mentions], **fields}
    return json.dumps(body, ensure_ascii=False)


def step(step_id: str, agent: str, operation: str, inputs: list[str] | None = None, **spec: Any) -> DraftStep:
    return DraftStep(step_id=step_id, agent=agent, operation=operation, spec=spec, inputs=inputs or [], objective=operation)


def plan(*steps: DraftStep) -> str:
    return json.dumps(PlanDraft(steps=list(steps), rationale="kế hoạch").model_dump(mode="json"), ensure_ascii=False)


LANDMARK_PLAN = plan(step("B1", "data", "fetch_units", scope=SCOPE),
                     step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                     step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]),
                     step("B4", "chart", "draw_chart", ["B2", "B3"]),
                     step("B5", "report", "draft_report", ["B2", "B3", "B4"]))
LANDMARK_INTENT = intent(["EXPLAIN"], phenomena=["bán chậm"])
