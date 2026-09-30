"""Code-enforced DAG execution over the Backend's own agent calls (WS5).

Each wave of a validated plan is one assistant step whose tool calls are `send_to_agent` calls (one per step), so
the Backend engine applies its usual rules: R3/R4 call accounting, per-(user, agent) queues, `max_depth`, the
wait-for graph (deadlock refusal) and failure propagation. Calls of one wave run concurrently in an
`asyncio.TaskGroup` (B2 ∥ B3); a wave starts only after the previous one has fully resolved (dependency barrier).

At every boundary the executor checks the reply: an `error: …` text (the engine refused the call or the peer failed)
→ `CALL_REJECTED`; not exactly one `AgentReport@1` for this step → `MALFORMED_REPORT`; each returned ref must be of a
type the catalog says the operation produces, pinned by hash, readable for this user (`artifact_get` is user-scoped)
and on the run's snapshot / semantic version — only then is it forwarded downstream.

Dependency modes: `all` (every dependency completed) and `any` (at least one; the failed ones are reported to the
step as `UPSTREAM_FAILED:<agent>`). Skipped steps are never called. The whole run has one deadline: on expiry the
pending calls are cancelled (TaskGroup), the state is persisted as `timed_out` and `AgentTimeoutError` is raised so
the engine fails the turn with DEADLINE_EXCEEDED and closes the open tool calls itself.

`run_state` (one artifact, a new version per transition) holds the plan, every step's status, timestamps, input and
output refs, error, limitations. A repeated invocation of the same plan (same task) reuses completed steps instead
of calling their agents again.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.catalog import AgentCatalog
from vdagent_contracts.catalogs import load_catalog
from vdagent_contracts.reports import AgentReport, parse_agent_report
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, InvocationContext, ToolCall

from .dag import TARGET_AGENTS, Plan, PlanStep, validate_plan

AGENT_VERSION = "0.2.0"
Tools = Any  # vdagent_contracts.step_inputs.Tools (call(name, args) -> dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StepState:
    step_id: str
    agent: str
    operation: str
    depends_on: list[str]
    status: str = "pending"  # pending | running | completed | failed | skipped | timed_out
    input_refs: list[dict[str, Any]] = field(default_factory=list)
    output_refs: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    limitations: list[str] = field(default_factory=list)
    partial: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    reused: bool = False


@dataclass
class RunOutcome:
    plan_id: str
    status: str  # completed | partial | failed | timed_out
    steps: dict[str, StepState]
    run_state_id: str | None = None


class DagExecutor:
    def __init__(self, ctx: InvocationContext, tools: Tools, *, catalogs: Mapping[str, AgentCatalog] | None = None,
                 timeout_s: float = 300.0, clock: Callable[[], str] = _now) -> None:
        self._ctx, self._tools, self._timeout_s, self._clock = ctx, tools, timeout_s, clock
        self._catalogs = dict(catalogs) if catalogs is not None else {a: load_catalog(a) for a in TARGET_AGENTS}
        self._state_id: str | None = None
        self._lock = asyncio.Lock()
        self._scope: dict[str, Any] = {}

    # ---- run ------------------------------------------------------------------------------------------------------

    async def run(self, plan: Plan) -> RunOutcome:
        waves = validate_plan(plan, self._catalogs)
        caller = await self._tools.call("get_user_context", {})
        self._scope = {"project_ids": list((caller.get("authorized_scope") or {}).get("project_ids") or []),
                       "zone_ids": list((caller.get("authorized_scope") or {}).get("zone_ids") or [])}
        states = {s.step_id: StepState(s.step_id, s.agent, s.operation, list(s.depends_on)) for s in plan.steps}
        await self._restore(plan, states)
        outcome = RunOutcome(plan.plan_id, "running", states)
        await self._persist(plan, outcome, waves)
        try:
            async with asyncio.timeout(self._timeout_s):
                for wave in waves:
                    await self._wave(plan, [plan.step(s) for s in wave], states)
                    await self._persist(plan, outcome, waves)
        except TimeoutError:
            for st in states.values():
                if st.status in ("running", "pending"):
                    st.status, st.finished_at = "timed_out", self._clock()
            outcome.status = "timed_out"
            await self._persist(plan, outcome, waves)
            raise AgentTimeoutError(f"plan {plan.plan_id} exceeded {self._timeout_s:g}s") from None
        outcome.status = _overall(plan, states)
        outcome.run_state_id = self._state_id
        await self._persist(plan, outcome, waves)
        return outcome

    async def _wave(self, plan: Plan, steps: list[PlanStep], states: dict[str, StepState]) -> None:
        runnable: list[tuple[PlanStep, ToolCall, str]] = []
        for step in steps:
            st = states[step.step_id]
            if st.status == "completed":
                continue  # reused from a previous invocation of this plan
            deps = [states[d] for d in step.depends_on]
            ok = [d for d in deps if d.status == "completed"]
            if (step.dependency_mode == "all" and len(ok) != len(deps)) or (step.dependency_mode == "any" and deps and not ok):
                st.status, st.finished_at = "skipped", self._clock()
                st.error = {"code": "DEPENDENCY_FAILED", "message": "required upstream step did not complete: "
                            + ", ".join(f"{d.step_id}={d.status}" for d in deps if d.status != "completed")}
                continue
            st.limitations = [f"UPSTREAM_FAILED:{d.agent}" for d in deps if d.status != "completed"]
            st.input_refs = [r for b in step.inputs if states[b.from_step].status == "completed"
                             for r in states[b.from_step].output_refs if r["artifact_type"] in b.artifact_types]
            try:
                spec = await self._resolve_spec(step, states)
            except LookupError as exc:
                st.status, st.finished_at = "failed", self._clock()
                st.error = {"code": "SPEC_UNRESOLVED", "message": str(exc)}
                continue
            message = self._stepspec(plan, step, spec, st.input_refs)
            call = ToolCall(id=f"call_{step.step_id}_{secrets.token_hex(4)}", name=SEND_TO_AGENT,
                            arguments_json=json.dumps({"agent": step.agent, "message": message}, ensure_ascii=False))
            runnable.append((step, call, message))
        if not runnable:
            return
        names = ", ".join(f"{s.step_id} {s.agent}.{s.operation}" for s, _, _ in runnable)
        await self._ctx.emit_assistant(f"[plan {plan.plan_id}] chạy {names}", [c for _, c, _ in runnable])
        async with asyncio.TaskGroup() as group:  # B2 and B3 run concurrently; the wave ends when all resolve
            for step, call, message in runnable:
                group.create_task(self._call(plan, step, call, message, states[step.step_id]))

    async def _call(self, plan: Plan, step: PlanStep, call: ToolCall, message: str, st: StepState) -> None:
        st.status, st.started_at = "running", self._clock()
        reply = await self._ctx.call_agent(call.id, step.agent, message)
        await self._ctx.emit_tool_result(call.id, reply)
        st.finished_at = self._clock()
        error = await self._check(plan, step, reply, st)
        if error is not None:
            st.status, st.error = "failed", error
        else:
            st.status = "completed"

    async def _check(self, plan: Plan, step: PlanStep, reply: str, st: StepState) -> dict[str, Any] | None:
        if reply.strip().startswith("error:"):
            return {"code": "CALL_REJECTED", "message": reply.strip()[:500]}
        report = parse_agent_report(reply)
        if not isinstance(report, AgentReport):
            return {"code": "MALFORMED_REPORT", "message": report.reason}
        if report.step_id != step.step_id or report.idempotency_key != f"{plan.plan_id}:{step.step_id}":
            return {"code": "MALFORMED_REPORT", "message": "the report answers another step"}
        st.limitations = sorted(set(st.limitations) | set(report.warnings))
        st.partial = report.partial
        if report.state != "completed":
            error = report.error
            return {"code": error.code if error else report.state.upper(), "message": error.message if error else report.summary,
                    "state": report.state}
        produces = set(self._catalogs[step.agent].operation(step.operation).produces)
        refs = []
        for ref in report.artifact_refs:
            if ref.artifact_type.value not in produces:
                return {"code": "REF_TYPE_UNEXPECTED", "message": f"{step.agent} returned a {ref.artifact_type.value}"}
            if ref.content_hash is None:
                return {"code": "REF_HASH_MISSING", "message": f"{ref.artifact_id} is not pinned"}
            try:
                env = await self._tools.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})
            except Exception:
                return {"code": "REF_NOT_FOUND", "message": f"{ref.artifact_id}@{ref.version} is not readable"}
            if env["content_hash"] != ref.content_hash:
                return {"code": "REF_HASH_MISMATCH", "message": f"{ref.artifact_id}@{ref.version}"}
            if env["snapshot_refs"] != [plan.snapshot_id]:
                return {"code": "REF_SNAPSHOT_MISMATCH", "message": f"{ref.artifact_id} is on {env['snapshot_refs']}"}
            if env["semantic_config_version"] != plan.semantic_config_version:
                return {"code": "REF_SEMANTIC_MISMATCH", "message": f"{ref.artifact_id} uses {env['semantic_config_version']}"}
            refs.append(ref.model_dump(mode="json"))
        if step.agent in ("data", "insight", "compare"):
            missing = produces - {r["artifact_type"] for r in refs}
            if missing:
                return {"code": "REF_MISSING", "message": f"{step.agent} did not return {sorted(missing)}"}
        if not refs:
            return {"code": "REF_MISSING", "message": f"{step.agent} returned no artifact"}
        st.output_refs = refs
        return None

    # ---- step messages ----------------------------------------------------------------------------------------------

    async def _resolve_spec(self, step: PlanStep, states: dict[str, StepState]) -> dict[str, Any]:
        spec = json.loads(json.dumps(dict(step.spec)))
        scope = spec.get("analysis_scope")
        if isinstance(scope, dict) and "$subject_scope_of" in scope:
            source = states[scope["$subject_scope_of"]]
            ref = next((r for r in source.output_refs if r["artifact_type"] == "dataset"), None)
            if ref is None:
                raise LookupError("no dataset to take the subject from")
            dataset = await self._tools.call("artifact_get", {"artifact_id": ref["artifact_id"], "version": ref["version"]})
            key = dataset["payload"]["population"]["subject_unit_key"]
            unit = next(u for u in dataset["payload"]["tables"]["dim_unit_master"] if u["unit_key"] == key)
            spec["analysis_scope"] = {"level": "UNIT", "project_ids": [unit["project_key"]], "unit_ids": [key]}
        return spec

    def _stepspec(self, plan: Plan, step: PlanStep, spec: dict[str, Any], input_refs: list[dict[str, Any]]) -> str:
        deadline = self._catalogs[step.agent].operation(step.operation).deadline_s
        return json.dumps({
            "contract": "StepSpec@1", "run_id": plan.run_id, "plan_id": plan.plan_id, "step_id": step.step_id,
            "idempotency_key": f"{plan.plan_id}:{step.step_id}", "operation": step.operation, "spec": spec,
            "user_context": {"user_id": self._ctx.user_id, "authorized_scope": self._scope},
            "snapshot_id": plan.snapshot_id, "semantic_config_version": plan.semantic_config_version,
            "input_refs": input_refs, "deadline_s": deadline, "original_question": plan.question,
        }, ensure_ascii=False)

    # ---- run_state ------------------------------------------------------------------------------------------------

    async def _restore(self, plan: Plan, states: dict[str, StepState]) -> None:
        listed = await self._tools.call("artifact_list", {"run_id": plan.run_id, "artifact_type": "run_state"})
        for summary in listed.get("artifacts", []):
            env = await self._tools.call("artifact_get", {"artifact_id": summary["artifact_id"]})
            if env["payload"].get("plan_id") != plan.plan_id:
                continue
            self._state_id = env["artifact_id"]
            for saved in env["payload"].get("steps", []):
                st = states.get(saved["step_id"])
                if st is not None and saved.get("status") == "completed":
                    for key in ("status", "input_refs", "output_refs", "limitations", "partial", "started_at", "finished_at"):
                        setattr(st, key, saved[key])
                    st.reused = True

    async def _persist(self, plan: Plan, outcome: RunOutcome, waves: list[list[str]]) -> None:
        async with self._lock:
            draft: dict[str, Any] = {
                "artifact_type": "run_state", "schema_version": "run_state@1", "status": "VALID",
                "producer": {"agent": "orchestrator", "agent_version": AGENT_VERSION},
                "snapshot_refs": [plan.snapshot_id], "semantic_config_version": plan.semantic_config_version,
                "payload": {"plan_id": plan.plan_id, "run_id": plan.run_id, "question": plan.question, "status": outcome.status,
                            "waves": waves, "plan": plan.to_json(), "updated_at": self._clock(),
                            "steps": [asdict(s) for s in outcome.steps.values()]},
            }
            if self._state_id is not None:
                draft["artifact_id"] = self._state_id
            stored = await self._tools.call("artifact_put", {"draft_json": canonical_json(draft)})
            self._state_id = stored["artifact_id"]
            outcome.run_state_id = self._state_id


def _overall(plan: Plan, states: dict[str, StepState]) -> str:
    data = [s for s in states.values() if s.agent == "data"]
    analyses = [s for s in states.values() if s.agent in ("insight", "compare")]
    if any(s.status != "completed" for s in data) or (analyses and not any(s.status == "completed" for s in analyses)):
        return "failed"
    if any(s.status != "completed" or s.partial or s.limitations for s in states.values()):
        return "partial"
    return "completed"
